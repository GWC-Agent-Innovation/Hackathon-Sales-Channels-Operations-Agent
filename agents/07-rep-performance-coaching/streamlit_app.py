import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import streamlit as st
from coaching_agent import data_store, agent_logic

st.set_page_config(page_title="Rep Performance & Coaching Agent", layout="wide")

STATUS_COLOR = {"Below Target": "🔴", "On Target": "🟢", "Exceeding Target": "🟡"}

data_store.load_all()

st.title("📊 Sales Rep Performance & Coaching Trigger Agent")
st.caption(
    "Watches rep performance against individual, role-specific targets and flags who needs "
    "coaching or recognition - instead of SLT manually reviewing every rep at period-end."
)

if st.sidebar.button("🔄 Reload data from CSV"):
    data_store.load_all()
    st.rerun()

tab_dashboard, tab_detail, tab_approval = st.tabs(
    ["📋 Rep Performance Dashboard", "📈 Rep Detail", "✅ Coaching / Recognition Approval"]
)

# =========================================================
# SCREEN 1: Rep Performance Dashboard (table)
# =========================================================
with tab_dashboard:
    st.subheader("Rep Performance Dashboard")
    rows = agent_logic.dashboard_rows()
    metrics = agent_logic.dashboard_metrics(rows)

    m1, m2 = st.columns(2)
    m1.metric("Reps below target", metrics["reps_below_target"])
    m2.metric("Avg gap size (below-target reps)", metrics["avg_gap_size"])

    st.dataframe(
        [
            {
                "Rep": r["name"],
                "Role": r["role"],
                "Primary Metric": "Conversion Ratio" if r["metric"] == "conversion_ratio" else "Churn Rate",
                "Latest": r["latest_value"],
                "Target": r["target_value"],
                "Gap": r["gap"],
                "Deal Value": f"${r['deal_value_latest']:,.0f}",
                "Deal Value vs Target": f"{r['deal_value_gap_pct']:+.1f}%" if r["deal_value_gap_pct"] is not None else "-",
                "Gap Flag": f"{STATUS_COLOR.get(r['status'], '')} {r['status']}",
            }
            for r in rows
        ],
        use_container_width=True, hide_index=True,
    )
    st.caption("Open Rep Detail to see the trend chart, or go to the Approval tab to act on a flagged rep.")

# =========================================================
# SCREEN 2: Rep Detail pop-up
# =========================================================
with tab_detail:
    st.subheader("Rep Detail")
    reps = data_store.list_reps()
    labels = [f"{r['name']} ({r['role']})" for r in reps]
    idx = st.selectbox("Select a rep", range(len(reps)), format_func=lambda i: labels[i], key="detail_rep")
    rep = reps[idx]
    g = agent_logic.gap_analysis(rep["id"])

    metric_label = "Conversion Ratio (%)" if g["metric"] == "conversion_ratio" else "Churn Rate (%)"
    st.markdown(f"**{rep['name']}** — {rep['role']} — manager: {rep['manager_name']}")
    st.markdown(f"### {STATUS_COLOR.get(g['status'], '')} {g['status']}")

    chart_data = {
        metric_label: g["metric_series"],
        "Target": [g["target_value"]] * len(g["periods"]),
    }
    st.line_chart({"period": g["periods"], **chart_data}, x="period")

    c1, c2, c3 = st.columns(3)
    c1.metric(metric_label, g["latest_value"], delta=g["gap"])
    c2.metric("Deal Value", f"${g['deal_value_latest']:,.0f}", delta=f"{g['deal_value_gap_pct']:+.1f}%")
    c3.metric("Activity Volume Trend", g["activity_trend"])

    st.markdown("**Gap breakdown:**")
    st.write(
        f"- Metric trend: **{g['metric_trend']}** over the last {len(g['periods'])} periods\n"
        f"- Activity volume trend: **{g['activity_trend']}**\n"
        f"- Deal value vs target: **{g['deal_value_gap_pct']:+.1f}%**"
    )

# =========================================================
# SCREEN 3: Coaching / Recognition Approval card
# =========================================================
with tab_approval:
    st.subheader("Coaching / Recognition Approval Card")
    reps = data_store.list_reps()
    labels = [f"{r['name']} ({r['role']})" for r in reps]
    idx2 = st.selectbox("Select a rep", range(len(reps)), format_func=lambda i: labels[i], key="approval_rep")
    rep = reps[idx2]
    review_key = f"review_{rep['id']}"

    if st.button("🔍 Run AI performance review", key=f"run_{rep['id']}"):
        with st.spinner("Diagnosing performance gap..."):
            st.session_state[review_key] = agent_logic.review_rep(rep["id"])

    review = st.session_state.get(review_key)
    if review:
        st.markdown(f"### {STATUS_COLOR.get(review['status'], '')} {review['status']}")
        with st.chat_message("assistant"):
            st.write(review["diagnosis"])

        if review["recommended_action"] == "Create Coaching Task":
            note = st.text_input("Comment (optional)", key=f"coach_note_{rep['id']}")
            if st.button("🎯 Create Coaching Task", key=f"coach_{rep['id']}"):
                task = agent_logic.create_coaching_task(rep["id"], note)
                st.success(f"Coaching task {task['id']} created and assigned to {task['manager_name']}.")
                st.session_state.pop(review_key, None)
                st.rerun()
        elif review["recommended_action"] == "Nominate for Recognition":
            note = st.text_input("Comment (optional)", key=f"rec_note_{rep['id']}")
            if st.button("🏆 Nominate for Recognition", key=f"rec_{rep['id']}"):
                nomination = agent_logic.nominate_recognition(rep["id"], note)
                st.success(f"Recognition nomination {nomination['id']} routed to SLT for review.")
                st.session_state.pop(review_key, None)
                st.rerun()
        else:
            st.info("This rep is on target - no coaching or recognition action recommended.")

    st.divider()
    st.subheader("Open Coaching Tasks (Manager Queue)")
    tasks = data_store.list_coaching_tasks()
    if tasks:
        st.dataframe(
            [{"Task ID": t["id"], "Rep": data_store.get_rep(t["rep_id"])["name"], "Manager": t["manager_name"],
              "Gap Summary": t["gap_summary"], "Created": t["created_date"], "Status": t["status"]} for t in tasks],
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No coaching tasks yet.")

    st.subheader("Recognition Nominations (SLT Review Queue)")
    nominations = data_store.list_recognition_nominations()
    if nominations:
        for n in nominations:
            with st.container(border=True):
                rep_name = data_store.get_rep(n["rep_id"])["name"]
                st.markdown(f"**{rep_name}** — {n['note']}")
                st.caption(f"Submitted {n['created_date']} — Status: {n['status']}")
                if n["status"] == "Pending SLT Review":
                    d1, d2 = st.columns(2)
                    if d1.button("✅ Approve", key=f"approve_{n['id']}"):
                        agent_logic.decide_recognition(n["id"], True)
                        st.rerun()
                    if d2.button("❌ Reject", key=f"reject_{n['id']}"):
                        agent_logic.decide_recognition(n["id"], False)
                        st.rerun()
    else:
        st.caption("No recognition nominations yet.")
