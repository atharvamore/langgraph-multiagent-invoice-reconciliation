# dashboard_app.py
import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os
import json

# Import our Chatbot Agent
from agents.chatbot_agent import ChatbotAgent
from agents.retrieval_agent import CompanyRetrievalAgent

# Import database initialization and seeding helpers
from database.seed_data import init_db, seed_company_invoices

DB_PATH = "database/company.db"
UPLOAD_DIR = "incoming_invoices"

st.set_page_config(layout="wide", page_title="AI Invoice Reconciliation Portal")
st.title("AI-Powered Invoice Reconciliation Dashboard")

# Ensure intake directory exists and initialize SQLite schema & baseline data on startup
os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(DB_PATH):
    try:
        init_db()
        seed_company_invoices()
    except Exception as e:
        st.warning(f"Database initialization warning: {e}")

# Initialize Chatbot Agent in Streamlit session state
if "chatbot" not in st.session_state:
    st.session_state.chatbot = ChatbotAgent()
if "retrieval_agent" not in st.session_state:
    st.session_state.retrieval_agent = CompanyRetrievalAgent()
if "messages" not in st.session_state:
    st.session_state.messages = []

# Database connection helper
def get_db_connection():
    """Open a SQLite connection that returns rows as dictionary-like objects."""
    if not os.path.exists(DB_PATH):
        try:
            init_db()
            seed_company_invoices()
        except Exception:
            pass
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Fetch system metrics
def load_metrics():
    """Load all processed invoice rows for dashboard metrics and charts."""
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM processed_invoices", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()

    # Auto-seed database if empty so charts render immediately on deployment
    if df.empty:
        try:
            init_db()
            seed_company_invoices()
            conn = get_db_connection()
            df = pd.read_sql_query("SELECT * FROM processed_invoices", conn)
            conn.close()
        except Exception:
            pass

    return df

# Fetch Human Review statistics from the audit log
def load_review_metrics():
    """Count the number of manually approved and manually rejected review items."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM human_reviews WHERE updated_state = 'APPROVED'")
        manually_approved = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM human_reviews WHERE updated_state = 'REJECTED'")
        manually_rejected = cursor.fetchone()[0]
    except Exception:
        manually_approved, manually_rejected = 0, 0
    finally:
        conn.close()
    return manually_approved, manually_rejected

df = load_metrics()
manually_approved, manually_rejected = load_review_metrics()


# --- SIDEBAR: AI CO-PILOT CHATBOT & DIRECT UPLOADER ---
with st.sidebar:
    st.header("AI Co-Pilot Assistant")
    st.write("Ask questions or upload invoice files directly to start processing.")

    if st.button("Refresh dashboard"):
        st.rerun()
        
    if st.button("Seed Sample Database & Invoices"):
        try:
            init_db()
            seed_company_invoices()
            st.success("Sample database seeded successfully!")
            st.rerun()
        except Exception as e:
            st.error(f"Seeding error: {e}")
    
    # Direct File Uploader
    uploaded_file = st.file_uploader(
        "Upload Invoice to Co-Pilot", 
        type=["pdf", "png", "jpg", "jpeg", "tiff", "txt"],
        help="Upload files directly to the automated ingestion folder."
    )
    
    if uploaded_file is not None:
        target_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
        file_state_key = f"processed_upload_{uploaded_file.name}"
        
        if file_state_key not in st.session_state:
            try:
                with open(target_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                st.session_state[file_state_key] = True
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"📥 **File Received**: I have received `{uploaded_file.name}` and routed it to the automated ingestion queue. The background daemon will process it shortly!"
                })
                st.rerun()
            except Exception as e:
                st.error(f"Failed to ingest file: {e}")

    st.markdown("---")
    
    # Chat history display
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input with real-time response streaming
    if user_prompt := st.chat_input("Ask me about invoices..."):
        with st.chat_message("user"):
            st.markdown(user_prompt)
        st.session_state.messages.append({"role": "user", "content": user_prompt})

        with st.chat_message("assistant"):
            response = st.write_stream(st.session_state.chatbot.converse_stream(user_prompt))
        st.session_state.messages.append({"role": "assistant", "content": response})


# --- MAIN INTERFACE: METRICS AND QUEUE ---
st.subheader("Live Dashboard Controls")
col_refresh_1, col_refresh_2 = st.columns([1, 4])
with col_refresh_1:
    if st.button("Refresh metrics and queue"):
        st.rerun()
with col_refresh_2:
    st.caption("Use this button after new invoices finish processing or after manual review actions.")

if df.empty:
    st.info("No invoice metrics available. Seed the database or run the pipeline to populate charts.")
else:
    # 1. SIX-COLUMN METRICS GRID
    total_invoices = len(df)
    approved = len(df[df["decision"] == "APPROVED"])
    review_needed = len(df[df["decision"] == "HUMAN_REVIEW"])
    rejected = len(df[df["decision"] == "REJECTED"])

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Processed Invoices", total_invoices)
    m2.metric("Total Approved", approved, delta=f"{approved/total_invoices*100:.1f}%" if total_invoices > 0 else None)
    m3.metric("Pending Review", review_needed)
    m4.metric("Auto-Rejected", rejected)
    m5.metric("Reviews Accepted", manually_approved, help="Invoices approved manually after review.")
    m6.metric("Reviews Rejected", manually_rejected, help="Invoices rejected manually after review.")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Invoice Reconciliation Breakdown")
        fig_pie = px.pie(df, names="decision", color="decision",
                         color_discrete_map={"APPROVED": "#2E7D32", "HUMAN_REVIEW": "#EF6C00", "REJECTED": "#C62828"},
                         hole=0.4)
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        st.subheader("Invoice Volume Timeline")
        df["date_only"] = pd.to_datetime(df["started_at"]).dt.date
        timeline_df = df.groupby("date_only").size().reset_index(name="Volume")
        fig_line = px.line(timeline_df, x="date_only", y="Volume", markers=True, labels={"date_only": "Date"})
        st.plotly_chart(fig_line, use_container_width=True)


    # --- HUMAN REVIEW ACTIONS SECTION ---
    st.markdown("---")
    st.subheader("Human Review Queue")
    queue_refresh_col, queue_hint_col = st.columns([1, 4])
    with queue_refresh_col:
        if st.button("Refresh queue", key="refresh_queue"):
            st.rerun()
    with queue_hint_col:
        st.caption("Reload this section after a pipeline run or reviewer action.")
    
    conn = get_db_connection()
    review_df = pd.read_sql_query("""
        SELECT processing_id, file_name, extracted_json, comments, started_at 
        FROM processed_invoices 
        WHERE decision = 'HUMAN_REVIEW' AND state = 'HUMAN_REVIEW'
    """, conn)
    conn.close()

    if review_df.empty:
        st.success("The human review queue is currently empty.")
    else:
        for idx, row in review_df.iterrows():
            processing_id = row["processing_id"]
            file_name = row["file_name"]
            system_comments = row["comments"]
            started_at = row["started_at"]
            
            # Parse client extracted JSON
            client_invoice = {}
            if row["extracted_json"]:
                try:
                    client_invoice = json.loads(row["extracted_json"])
                except Exception:
                    pass
            
            # Fetch company reference record using the same ranked matcher as the pipeline
            ref_invoice = None
            ref_items = []
            
            if client_invoice:
                try:
                    ref_invoice = st.session_state.retrieval_agent.retrieve_reference_invoice(
                        client_invoice, processing_id
                    )
                    if ref_invoice:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (ref_invoice["id"],))
                        ref_items = [dict(r) for r in cursor.fetchall()]
                        conn.close()
                except Exception as e:
                    st.warning(f"Reference lookup failed: {e}")

            with st.container():
                st.markdown(f"### Processing ID: `{processing_id}` ({file_name})")
                st.info(f"**Rejection Flag:** {system_comments} | **Received:** {started_at}")
                
                col_client, col_ref = st.columns(2)
                
                # COLUMN 1: Client Invoice
                with col_client:
                    st.markdown("#### 📥 Extracted Client Invoice")
                    if client_invoice:
                        st.write(f"**Vendor Name:** `{client_invoice.get('vendor', 'UNKNOWN')}`")
                        st.write(f"**Invoice No:** `{client_invoice.get('invoice_no', 'UNKNOWN')}`")
                        st.write(f"**Invoice Date:** `{client_invoice.get('invoice_date', 'UNKNOWN')}`")
                        st.write(f"**Tax/GST Charged:** `${client_invoice.get('gst', 0.0):,.2f}`")
                        st.write(f"**Total Amount Stated:** `${client_invoice.get('amount', 0.0):,.2f}`")
                        
                        st.markdown("**Itemized Product Lines:**")
                        products_df = pd.DataFrame(client_invoice.get("products", []))
                        if not products_df.empty:
                            st.dataframe(products_df[["name", "quantity", "unit_price", "total_price"]], use_container_width=True, hide_index=True)
                        else:
                            st.caption("No product items extracted.")
                    else:
                        st.error("No extracted details found.")

                # COLUMN 2: Company Reference Invoice
                with col_ref:
                    st.markdown("#### 🏢 Company Database Reference")
                    if ref_invoice:
                        st.write(f"**Vendor Name:** `{ref_invoice.get('vendor')}`")
                        st.write(f"**Invoice No:** `{ref_invoice.get('invoice_no')}`")
                        st.write(f"**Invoice Date:** `{ref_invoice.get('invoice_date')}`")
                        st.write(f"**Tax/GST Reference:** `${ref_invoice.get('gst', 0.0):,.2f}`")
                        st.write(f"**Total Reference Amount:** `${ref_invoice.get('amount', 0.0):,.2f}`")
                        
                        st.markdown("**Itemized Reference Lines:**")
                        ref_items_df = pd.DataFrame(ref_items)
                        if not ref_items_df.empty:
                            st.dataframe(ref_items_df[["name", "quantity", "unit_price", "total_price"]], use_container_width=True, hide_index=True)
                        else:
                            st.caption("No product items recorded.")
                    else:
                        st.warning("No matching company reference invoice found in SQL.")

                st.markdown("---")
                
                # Action inputs
                comments = st.text_input("Reviewer Comments / Audit Notes", key=f"comm_{processing_id}")
                action_col1, action_col2 = st.columns([1, 8])
                
                with action_col1:
                    if st.button("Approve", key=f"app_{processing_id}"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE processed_invoices 
                            SET state = 'COMPLETED', decision = 'APPROVED', comments = ?
                            WHERE processing_id = ?
                        """, (f"Reviewer Approved: {comments}", processing_id))
                        cursor.execute("""
                            INSERT INTO human_reviews (processing_id, reviewer_comments, original_state, updated_state)
                            VALUES (?, ?, 'HUMAN_REVIEW', 'APPROVED')
                        """, (processing_id, comments))
                        conn.commit()
                        conn.close()
                        st.rerun()
                
                with action_col2:
                    if st.button("Reject", key=f"rej_{processing_id}"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE processed_invoices 
                            SET state = 'COMPLETED', decision = 'REJECTED', comments = ?
                            WHERE processing_id = ?
                        """, (f"Reviewer Rejected: {comments}", processing_id))
                        cursor.execute("""
                            INSERT INTO human_reviews (processing_id, reviewer_comments, original_state, updated_state)
                            VALUES (?, ?, 'HUMAN_REVIEW', 'REJECTED')
                        """, (processing_id, comments))
                        conn.commit()
                        conn.close()
                        st.rerun()
                st.markdown("<hr style='border:1px dashed #ccc'>", unsafe_allow_html=True)
