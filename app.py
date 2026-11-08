"""Streamlit interface for the ITV7 settlement audit engine."""

from datetime import date

import streamlit as st

from settlement import build_verified_totals, parse_settlement_table, validate


st.set_page_config(page_title="ITV7 Audit Engine", page_icon="🏇", layout="wide")
st.title("ITV7 Settlement Audit")
st.caption("Parse a settlement table and independently verify the arithmetic.")

with st.sidebar:
    meeting = st.text_input("Meeting", placeholder="e.g. Cheltenham")
    audit_date = st.date_input("Date", value=date.today())

settlement_text = st.text_area(
    "Settlement table",
    height=360,
    placeholder="Paste the §28.1 settlement table here...",
    help="Paste the full settlement table, including race headers, place terms, and selections.",
)

if st.button("Run audit", type="primary", disabled=not settlement_text.strip()):
    rows, warnings = parse_settlement_table(settlement_text)

    if not rows:
        st.error("No settlement rows were parsed. Check the table format and try again.")
    else:
        totals = build_verified_totals(rows, meeting.strip() or "Meeting", audit_date.isoformat())
        st.subheader("Verified totals")
        st.code(totals, language="text")

        st.subheader("Parsed selections")
        st.dataframe(
            [
                {
                    "Race": row.race_id,
                    "Tier": row.tier,
                    "Horse": row.horse,
                    "Declared": row.declared,
                    "Result": row.result,
                    "SP": row.sp,
                    "Stake (£)": f"{row.stake:.2f}",
                    "Return (£)": f"{row.return_amount:.2f}",
                    "P/L (£)": f"{row.pnl:+.2f}",
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )

        errors = validate(rows)
        if errors:
            st.error("Validation issues found")
            for error in errors:
                st.write(f"- {error}")
        else:
            st.success("Validation passed.")

        if warnings:
            with st.expander(f"Parser warnings ({len(warnings)})"):
                for warning in warnings:
                    st.write(f"- {warning}")
