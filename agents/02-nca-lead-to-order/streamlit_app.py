import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import streamlit as st
from nca_agent import data_store, agent_logic

st.set_page_config(page_title="NCA Lead-to-Order Assistant", layout="wide")

STAGE_ICONS = {"complete": "✅", "current": "🟢", "pending": "⚪"}

data_store.load_all()

st.title("🤝 NCA Lead-to-Order Conversion Assistant")
st.caption(
    "Helps NCA reps close deals as fast as possible: tells them what's needed to progress "
    "each deal, prioritizes their daily action list across all open opportunities, and "
    "turns call notes into CRM updates - all with rep confirmation before anything is written."
)

if st.sidebar.button("🔄 Reload data from CSV"):
    data_store.load_all()
    st.rerun()

tab_assistant, tab_daily, tab_notes = st.tabs(
    ["💬 Deal Assistant", "📋 Daily Priorities", "📝 Log Meeting / Call Note"]
)

# =========================================================
# TAB 1: Conversational per-deal assistant (fields + gates)
# =========================================================
with tab_assistant:
    opportunities = data_store.list_opportunities()
    labels = [f"{o['account_name']} — {o['stage']} (${o['deal_value']:,.0f})" for o in opportunities]
    idx = st.selectbox("Select an opportunity", range(len(opportunities)), format_func=lambda i: labels[i])
    opp = opportunities[idx]
    opp_id = opp["id"]

    col_chat, col_side = st.columns([3, 2])

    with col_side:
        st.subheader("Stage Progress")
        timeline = agent_logic.get_timeline(opp_id)
        for stage in timeline["stages"]:
            st.write(f"{STAGE_ICONS.get(stage['status'], '⚪')}  {stage['name']}")
        st.divider()
        st.markdown(f"**Account:** {opp['account_name']}  \n**Rep:** {opp['rep_name']}")
        st.markdown(f"**Product:** {opp['product_line']}  \n**Deal value:** ${opp['deal_value']:,.0f}")
        st.markdown("**Recent activity:**")
        for act in data_store.get_activities(opp_id)[:3]:
            note = f" (promised: {act['commitment']})" if act.get("commitment") else ""
            st.caption(f"{act['activity_date']} · {act['activity_type']} — {act['summary']}{note}")

        commitments = agent_logic.open_commitments(opp_id)
        if commitments:
            st.warning("⚠️ Open commitments not yet fulfilled:")
            for c in commitments:
                cc1, cc2 = st.columns([3, 1])
                cc1.write(f"- {c['commitment']} ({c['activity_date']})")
                if cc2.button("Mark done", key=f"fulfill_{c['id']}"):
                    data_store.mark_commitment_fulfilled(c["id"], opp_id)
                    st.rerun()

        if opp["stage"] not in ("Closed Won", "Closed Lost"):
            with st.expander("Mark this deal Closed Lost"):
                reason = st.text_input("Reason", key=f"lost_reason_{opp_id}")
                if st.button("Confirm Closed Lost", key=f"lost_btn_{opp_id}") and reason:
                    agent_logic.mark_closed_lost(opp_id, reason)
                    st.rerun()

    with col_chat:
        st.subheader("Conversational Assistant")
        suggestion_key = f"suggestion_{opp_id}"
        document_key = f"document_draft_{opp_id}"

        if st.button("💬 Ask agent what's needed to progress", key=f"ask_{opp_id}"):
            with st.spinner("Checking required fields and activity history..."):
                st.session_state[suggestion_key] = agent_logic.get_suggestion(opp_id)
                st.session_state.pop(document_key, None)

        suggestion = st.session_state.get(suggestion_key)
        if suggestion:
            with st.chat_message("assistant"):
                st.write(suggestion["message"])

            if not suggestion["next_stage"]:
                pass
            elif suggestion["missing"]:
                st.markdown(f"**Outstanding to reach `{suggestion['next_stage']}`:**")
                for m in suggestion["missing"]:
                    mc1, mc2 = st.columns([3, 1])
                    mc1.write(f"- {m['label']}")
                    if m["field"] == "proposal_shared_date":
                        if mc2.button("Draft it", key=f"draft_{opp_id}_{m['field']}"):
                            with st.spinner("Drafting proposal..."):
                                st.session_state[document_key] = agent_logic.generate_document_preview(opp_id)
                    else:
                        if mc2.button("Mark done", key=f"confirm_{opp_id}_{m['field']}"):
                            agent_logic.confirm_field(opp_id, m["field"])
                            st.session_state.pop(suggestion_key, None)
                            st.rerun()
            else:
                if st.button(f"✅ Confirm: advance to {suggestion['next_stage']}", key=f"advance_{opp_id}"):
                    agent_logic.advance_stage_if_ready(opp_id)
                    st.session_state.pop(suggestion_key, None)
                    st.rerun()

        document = st.session_state.get(document_key)
        if document:
            st.divider()
            st.subheader("Generated Proposal Preview")
            edited_body = st.text_area("Proposal body (edit before sending)", document["body"], height=200, key=f"doc_body_{opp_id}")
            if st.button("✅ Approve & Send Proposal (advances to Negotiation)", key=f"send_doc_{opp_id}"):
                edited = {**document, "body": edited_body}
                agent_logic.confirm_proposal_sent(opp_id, edited)
                st.session_state.pop(document_key, None)
                st.session_state.pop(suggestion_key, None)
                st.rerun()

# =========================================================
# TAB 2: Daily action-prioritization assistant
# =========================================================
with tab_daily:
    st.subheader("Daily Action Prioritization")
    st.caption("Instead of manually reviewing every open opportunity, get a ranked list of what to do next.")
    reps = data_store.list_reps()
    rep = st.selectbox("Rep", reps, key="daily_rep")
    if st.button("▶️ Run daily review", key="run_daily"):
        with st.spinner(f"Reviewing all open opportunities for {rep}..."):
            st.session_state["daily_results"] = agent_logic.get_daily_priorities(rep)

    results = st.session_state.get("daily_results")
    if results:
        for r in results:
            with st.container(border=True):
                flags = []
                if r["commitments"]:
                    flags.append("⚠️ unfulfilled commitment")
                if r["stale_days"] >= 10:
                    flags.append(f"🥶 stale {r['stale_days']}d")
                flag_text = "  ".join(flags)
                st.markdown(f"**{r['account_name']}** · {r['stage']} · ${r['deal_value']:,.0f}  {flag_text}")
                st.write(f"👉 {r['recommended_action']}")
                st.caption(f"Based on: {r['pattern']}")

# =========================================================
# TAB 3: Meeting/call note ingestion
# =========================================================
with tab_notes:
    st.subheader("Log a Meeting or Call")
    st.caption("Paste in notes from a call/meeting (or a recording transcript) - the agent extracts what changed.")
    opportunities = data_store.list_opportunities()
    labels = [f"{o['account_name']} — {o['stage']}" for o in opportunities]
    idx2 = st.selectbox("Opportunity", range(len(opportunities)), format_func=lambda i: labels[i], key="notes_opp")
    note_opp = opportunities[idx2]
    note_text = st.text_area("What happened in the call/meeting?", height=120, key="note_text")

    if st.button("🔍 Analyze note", key="analyze_note") and note_text.strip():
        with st.spinner("Extracting CRM updates from the note..."):
            st.session_state["note_analysis"] = agent_logic.analyze_meeting_note(note_opp["id"], note_text)

    analysis = st.session_state.get("note_analysis")
    if analysis:
        st.markdown(f"**Summary to log:** {analysis['summary']}")
        confirmed_fields = []
        if analysis["suggested_fields"]:
            st.markdown("**Fields this note appears to satisfy** (uncheck any that aren't actually confirmed):")
            for m in analysis["suggested_fields"]:
                if st.checkbox(m["label"], value=True, key=f"note_field_{m['field']}"):
                    confirmed_fields.append(m["field"])
        else:
            st.caption("No pending fields detected as satisfied by this note.")

        commitment = st.text_input(
            "New commitment made to the customer (edit/clear if wrong)",
            value=analysis["suggested_commitment"], key="note_commitment",
        )

        if st.button("✅ Confirm & save to CRM", key="save_note"):
            result = agent_logic.apply_meeting_note(note_opp["id"], analysis["summary"], confirmed_fields, commitment)
            st.session_state.pop("note_analysis", None)
            msg = f"Activity logged for {note_opp['account_name']}."
            if result["advanced"]:
                msg += f" Stage advanced to **{result['opportunity']['stage']}**."
            st.success(msg)
