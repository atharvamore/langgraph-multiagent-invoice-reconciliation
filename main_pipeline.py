# main_pipeline.py
import os
import sqlite3
import json
from typing import TypedDict, List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from database.seed_data import init_db, seed_company_invoices
from agents.intake_agent import IntakeAgent
from agents.file_detection_agent import FileDetectionAgent
from agents.extraction_agent import ExtractionAgent
from agents.extraction_agent_llm import StructuredExtractionAgent
from guardrails.validators import GuardrailValidator
from agents.validation_agent import ValidationAgent
from agents.retrieval_agent import CompanyRetrievalAgent
from agents.matching_agent import MatchingAgent
from agents.decision_agent import DecisionAgent
from utils.logger import setup_logger

logger = setup_logger("MainPipeline")


class PipelineState(TypedDict):
    input_file_path: str
    processing_id: Optional[str]
    working_file: Optional[str]
    raw_text: Optional[str]
    extracted_json: Optional[Dict[str, Any]]
    passed_guardrails: bool
    guardrail_issues: List[str]
    passed_business: bool
    business_issues: List[str]
    reference_invoice: Optional[Dict[str, Any]]
    match_report: Optional[Dict[str, Any]]
    decision: Optional[str]
    error: Optional[str]


class ReconciliationPipelineEngine:
    def __init__(self):
        """Initialize database, agents, and compile the LangGraph state machine workflow."""
        logger.info("Starting Enterprise Ingestion Engine with LangGraph Orchestration...")
        init_db()
        seed_company_invoices()
        
        # Load Cognitive Agents
        self.intake_agent = IntakeAgent()
        self.file_detection_agent = FileDetectionAgent()
        self.extraction_agent = ExtractionAgent()
        self.llm_extractor = StructuredExtractionAgent()
        self.guardrail_validator = GuardrailValidator()
        self.validation_agent = ValidationAgent()
        self.retrieval_agent = CompanyRetrievalAgent()
        self.matching_agent = MatchingAgent()
        self.decision_agent = DecisionAgent()

        # Build LangGraph State Machine
        self.checkpointer = MemorySaver()
        self.app = self._build_langgraph_workflow()

    def _build_langgraph_workflow(self):
        """Constructs and compiles the LangGraph StateGraph pipeline."""
        workflow = StateGraph(PipelineState)

        # Register nodes
        workflow.add_node("intake", self._intake_node)
        workflow.add_node("extraction", self._extraction_node)
        workflow.add_node("validation", self._validation_node)
        workflow.add_node("retrieval", self._retrieval_node)
        workflow.add_node("matching", self._matching_node)
        workflow.add_node("decision", self._decision_node)

        # Set entry point
        workflow.add_edge(START, "intake")

        # Define state routing edges
        workflow.add_conditional_edges("intake", self._check_error, {"continue": "extraction", "abort": END})
        workflow.add_conditional_edges("extraction", self._check_error, {"continue": "validation", "abort": END})
        workflow.add_conditional_edges("validation", self._check_error, {"continue": "retrieval", "abort": END})
        workflow.add_conditional_edges("retrieval", self._check_error, {"continue": "matching", "abort": END})
        workflow.add_edge("matching", "decision")
        workflow.add_edge("decision", END)

        return workflow.compile(checkpointer=self.checkpointer)

    def _check_error(self, state: PipelineState) -> str:
        """Edge condition to determine if graph execution should proceed or abort."""
        if state.get("error"):
            return "abort"
        return "continue"

    # --- NODE IMPLEMENTATIONS ---
    def _intake_node(self, state: PipelineState) -> PipelineState:
        input_path = state["input_file_path"]
        logger.info(f"[LangGraph Node: Intake] Processing input file: {input_path}")
        
        processing_id, working_file = self.intake_agent.register_new_file(input_path)
        file_analysis = self.file_detection_agent.analyze_file(working_file)
        
        if not file_analysis["is_supported"]:
            msg = f"Unsupported file format: {file_analysis['error']}"
            self._persist_abort(processing_id, "REJECTED", msg)
            return {**state, "processing_id": processing_id, "working_file": working_file, "error": msg}

        return {**state, "processing_id": processing_id, "working_file": working_file, "error": None}

    def _extraction_node(self, state: PipelineState) -> PipelineState:
        processing_id = state["processing_id"]
        working_file = state["working_file"]
        logger.info(f"[LangGraph Node: Extraction] Processing ID: {processing_id}")

        try:
            file_analysis = self.file_detection_agent.analyze_file(working_file)
            needs_ocr = file_analysis.get("requires_ocr", False)
            raw_text = self.extraction_agent.extract_raw_text(working_file, needs_ocr, processing_id)
            
            # Structured Extraction via Groq Vision / Text
            extracted_json = self.llm_extractor.parse_to_structured_json(
                raw_text, processing_id, file_path=working_file
            )
            return {**state, "raw_text": raw_text, "extracted_json": extracted_json, "error": None}
        except Exception as e:
            msg = f"Extraction failure: {str(e)}"
            self._persist_abort(processing_id, "REJECTED", msg)
            return {**state, "error": msg}

    def _validation_node(self, state: PipelineState) -> PipelineState:
        processing_id = state["processing_id"]
        extracted_json = state["extracted_json"]
        logger.info(f"[LangGraph Node: Validation] Processing ID: {processing_id}")

        passed_guardrails, guardrail_issues = self.guardrail_validator.audit_and_validate(
            extracted_json, processing_id
        )
        if not passed_guardrails:
            msg = f"Guardrail Failure: {'; '.join(guardrail_issues)}"
            self._persist_abort(processing_id, "REJECTED", msg)
            return {**state, "passed_guardrails": False, "guardrail_issues": guardrail_issues, "error": msg}

        passed_business, business_issues = self.validation_agent.run_business_validation(
            extracted_json, processing_id
        )
        if not passed_business:
            msg = f"Validation Failure: {'; '.join(business_issues)}"
            self._persist_abort(processing_id, "REJECTED", msg)
            return {**state, "passed_business": False, "business_issues": business_issues, "error": msg}

        return {
            **state,
            "passed_guardrails": True,
            "guardrail_issues": [],
            "passed_business": True,
            "business_issues": [],
            "error": None
        }

    def _retrieval_node(self, state: PipelineState) -> PipelineState:
        processing_id = state["processing_id"]
        extracted_json = state["extracted_json"]
        working_file = state["working_file"]
        logger.info(f"[LangGraph Node: Retrieval] Processing ID: {processing_id}")

        reference_invoice = self.retrieval_agent.retrieve_reference_invoice(extracted_json, processing_id)
        if not reference_invoice:
            msg = "Reconciliation Match target missing."
            self._persist_abort(processing_id, "HUMAN_REVIEW", msg)
            shutil_dest = os.path.join("human_review", os.path.basename(working_file))
            if os.path.exists(working_file):
                import shutil
                shutil.move(working_file, shutil_dest)
            return {**state, "reference_invoice": None, "error": msg}

        return {**state, "reference_invoice": reference_invoice, "error": None}

    def _matching_node(self, state: PipelineState) -> PipelineState:
        processing_id = state["processing_id"]
        extracted_json = state["extracted_json"]
        reference_invoice = state["reference_invoice"]
        logger.info(f"[LangGraph Node: Matching] Processing ID: {processing_id}")

        match_report = self.matching_agent.compare_invoices(extracted_json, reference_invoice, processing_id)
        return {**state, "match_report": match_report}

    def _decision_node(self, state: PipelineState) -> PipelineState:
        processing_id = state["processing_id"]
        match_report = state["match_report"]
        working_file = state["working_file"]
        logger.info(f"[LangGraph Node: Decision] Processing ID: {processing_id}")

        decision = self.decision_agent.make_decision(match_report, processing_id, working_file)
        return {**state, "decision": decision}

    def _persist_abort(self, processing_id: str, state_decision: str, msg: str):
        """Persist terminal state and failure comment to database."""
        logger.error(f"[{processing_id}] Workflow aborted. Reason: {msg}")
        conn = sqlite3.connect("database/company.db")
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE processed_invoices
            SET state = 'COMPLETED', decision = ?, comments = ?, updated_at = CURRENT_TIMESTAMP
            WHERE processing_id = ?
        """, (state_decision, msg, processing_id))
        conn.commit()
        conn.close()

    def process_document(self, input_file_path: str) -> bool:
        """Executes the invoice reconciliation process using the compiled LangGraph state machine."""
        logger.info(f"Starting LangGraph execution flow for: {input_file_path}")
        
        initial_state: PipelineState = {
            "input_file_path": input_file_path,
            "processing_id": None,
            "working_file": None,
            "raw_text": None,
            "extracted_json": None,
            "passed_guardrails": False,
            "guardrail_issues": [],
            "passed_business": False,
            "business_issues": [],
            "reference_invoice": None,
            "match_report": None,
            "decision": None,
            "error": None
        }

        # Config with thread_id for checkpoint tracking
        config = {"configurable": {"thread_id": os.path.basename(input_file_path)}}
        final_state = self.app.invoke(initial_state, config=config)

        if final_state.get("error"):
            logger.warning(f"LangGraph execution halted with error: {final_state['error']}")
            return False

        logger.info(f"LangGraph execution completed successfully. Decision: {final_state.get('decision')}")
        return True


if __name__ == "__main__":
    engine = ReconciliationPipelineEngine()
    demo_file = "incoming_invoices/demo_invoice.txt"
    if os.path.exists(demo_file):
        engine.process_document(demo_file)
