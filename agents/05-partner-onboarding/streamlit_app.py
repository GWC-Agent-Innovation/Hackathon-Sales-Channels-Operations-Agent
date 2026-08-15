import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import streamlit as st
from partner_agent import data_store, agent_logic

st.set_page_config(page_title="Partner Onboarding Agent", layout="wide")

STATUS_COLOR = {"Cleared": "🟢", "Exception": "🟠", "Info Requested": "🔵", "Approved": "✅", "Rejected": "🔴"}

data_store.load_all()

st.title("🤝 Distributor & Reseller (MSP) Partner Onboarding Agent")
st.caption(
    "Validates new partner applications against the correct track (Distributor vs. Reseller/MSP) "
    "and tier criteria, flags channel conflicts, and provisions on Channel Manager approval."
)

if st.sidebar.button("🔄 Reload data from CSV"):
    data_store.load_all()
    st.rerun()

with st.sidebar.expander("📐 Program criteria reference"):
    for track in ("Distributor", "Reseller/MSP"):
        st.markdown(f"**{track}**")
        for c in data_store.criteria_for_track(track):
            reqs = []
            if c["requires_wholesale_only"]:
                reqs.append("wholesale-only")
            if c["requires_direct_selling"]:
                reqs.append("direct-selling")
            if c["requires_managed_services"]:
                reqs.append("managed services required")
            st.caption(
                f"{c['tier']}: min {c['min_volume_or_accounts']}, {c['discount_pct']:.0f}% discount"
                + (f" ({', '.join(reqs)})" if reqs else "")
            )

tab_form, tab_queue, tab_approval = st.tabs(
    ["📝 Partner Application Form", "📋 Applications Queue", "✅ Approval Card"]
)

# =========================================================
# SCREEN 1: Partner Application Form
# =========================================================
with tab_form:
    st.subheader("New Partner Application")
    st.caption("Applicant submits company details and requested track. Fields adapt to the track selected.")

    track_choice = st.selectbox("Requested track", ["Distributor", "Reseller/MSP"], key="form_track")

    with st.form("partner_application_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        company_name = c1.text_input("Company name")
        geography = c2.text_input("Geography")
        contact_name = c1.text_input("Contact name")
        contact_email = c2.text_input("Contact email")

        st.divider()
        if track_choice == "Distributor":
            st.markdown("**Distributor-specific details**")
            is_wholesale_only = st.checkbox(
                "This business is wholesale-only (never sells directly to end customers)", value=True
            )
            sells_direct = False
            has_managed_services = False
            volume_or_accounts = st.number_input(
                "Approximate wholesale volume (units/scale used for tiering)", min_value=0, value=20, step=1
            )
        else:
            st.markdown("**Reseller/MSP-specific details**")
            sells_direct = st.checkbox("This business sells directly to end customers", value=True)
            is_wholesale_only = False
            has_managed_services = st.checkbox("Has a managed-services / dedicated technical support capability")
            volume_or_accounts = st.number_input(
                "Number of SMB accounts currently served", min_value=0, value=10, step=1
            )

        notes = st.text_area("Additional notes (optional)")
        submitted = st.form_submit_button("Submit application")

        if submitted:
            if not company_name or not contact_name or not contact_email or not geography:
                st.error("Please fill in company name, contact name, contact email, and geography.")
            else:
                new_app = agent_logic.submit_application(
                    company_name=company_name, contact_name=contact_name, contact_email=contact_email,
                    requested_track=track_choice, geography=geography,
                    is_wholesale_only=is_wholesale_only, sells_direct=sells_direct,
                    has_managed_services=has_managed_services, volume_or_accounts=int(volume_or_accounts),
                    notes=notes,
                )
                st.success(f"Application {new_app['id']} submitted for {new_app['company_name']}. Check the Applications Queue.")

# =========================================================
# SCREEN 2: Applications Queue (table)
# =========================================================
with tab_queue:
    st.subheader("Applications Queue")
    queue = agent_logic.list_queue()

    m1, m2, m3 = st.columns(3)
    m1.metric("Applications this month", queue["metrics"]["applications_this_month"])
    for i, (track, rate) in enumerate(queue["metrics"]["approval_rate_by_track"].items()):
        (m2 if i == 0 else m3).metric(f"Approval rate — {track}", f"{rate}%")

    st.dataframe(
        [
            {
                "Application ID": r["id"],
                "Applicant": r["company_name"],
                "Requested Track": r["requested_track"],
                "Program-Criteria Match": f"{STATUS_COLOR.get(r['match_status'], '')} {r['match_status']}",
                "Current Status": r["current_status"],
                "Submitted": r["submitted_date"],
            }
            for r in queue["rows"]
        ],
        use_container_width=True, hide_index=True,
    )
    st.caption("Open the Approval Card tab and select an application to review and act on it.")

# =========================================================
# SCREEN 3: Approval card
# =========================================================
with tab_approval:
    st.subheader("Approval Card")
    applications = data_store.list_applications()
    labels = [f"{a['company_name']} — requested {a['requested_track']} ({a['status']})" for a in applications]
    idx = st.selectbox("Select an application", range(len(applications)), format_func=lambda i: labels[i])
    app = applications[idx]
    app_id = app["id"]

    col_review, col_side = st.columns([3, 2])

    with col_side:
        st.markdown("**Application Details**")
        st.markdown(f"**Company:** {app['company_name']}  \n**Contact:** {app['contact_name']} ({app['contact_email']})")
        st.markdown(f"**Geography:** {app['geography']}  \n**Requested track:** {app['requested_track']}")
        st.markdown(f"**Wholesale-only:** {app['is_wholesale_only']}  \n**Sells direct:** {app['sells_direct']}")
        st.markdown(f"**Managed services:** {app['has_managed_services']}  \n**Volume/accounts:** {app['volume_or_accounts']}")
        st.markdown(f"**Status:** {STATUS_COLOR.get(app['status'], '')} {app['status']}")
        if app.get("assigned_track"):
            st.markdown(f"**Assigned:** {app['assigned_track']} / {app['assigned_tier']}")
        st.caption(app["notes"])

    with col_review:
        review_key = f"review_{app_id}"

        if st.button("🔍 Run AI classification review", key=f"run_{app_id}"):
            with st.spinner("Checking track/tier criteria and channel conflicts..."):
                st.session_state[review_key] = agent_logic.review_application(app_id)

        review = st.session_state.get(review_key)
        if review:
            status_icon = STATUS_COLOR.get(review["status"], "")
            st.markdown(f"### {status_icon} {review['status']}")
            with st.chat_message("assistant"):
                st.write(review["summary"])

            st.markdown(f"**Correct track (by attributes):** {review['correct_track']}")
            if review["track_mismatch"]:
                st.warning(f"Requested '{review['requested_track']}' but attributes fit '{review['correct_track']}'.")
            if review["recommended_tier"]:
                t = review["recommended_tier"]
                st.info(f"Recommended: {t['track']} / {t['tier']} tier — {t['discount_pct']:.0f}% discount schedule")
            else:
                st.warning("Does not meet the minimum volume/account threshold for any tier yet.")
            if review["conflict"]:
                st.error(f"⚠️ Channel conflict: {review['conflict']['conflict_detail']}")

            st.markdown("**Reasons:**")
            for r in review["reasons"]:
                st.caption(f"- {r}")

            if app["status"] == "Pending":
                st.divider()
                st.markdown("**Approve into Track/Tier / Reject / Request more info**")
                default_track = review["recommended_tier"]["track"] if review["recommended_tier"] else review["correct_track"]
                default_tier = review["recommended_tier"]["tier"] if review["recommended_tier"] else None
                track_options = ["Distributor", "Reseller/MSP"]
                track_sel = st.selectbox(
                    "Track", track_options,
                    index=track_options.index(default_track) if default_track in track_options else 0,
                    key=f"track_{app_id}",
                )
                tier_options = [c["tier"] for c in data_store.criteria_for_track(track_sel)]
                tier_sel = st.selectbox(
                    "Tier", tier_options,
                    index=tier_options.index(default_tier) if default_tier in tier_options else 0,
                    key=f"tier_{app_id}",
                )
                note = st.text_input("Comment (optional)", key=f"note_{app_id}")

                c1, c2, c3 = st.columns(3)
                if c1.button("✅ Approve into Track/Tier", key=f"approve_{app_id}"):
                    result = agent_logic.approve_application(app_id, track_sel, tier_sel, note)
                    st.session_state.pop(review_key, None)
                    st.success(result["provisioning"]["notification"])
                    st.rerun()
                if c2.button("❌ Reject", key=f"reject_{app_id}"):
                    agent_logic.reject_application(app_id, note or "Did not meet program criteria")
                    st.session_state.pop(review_key, None)
                    st.rerun()
                if c3.button("ℹ️ Request more info", key=f"moreinfo_{app_id}"):
                    agent_logic.request_more_info(app_id, note or "Please clarify sales model and account volume")
                    st.session_state.pop(review_key, None)
                    st.rerun()
            else:
                st.success(f"This application is already {app['status']}.")
