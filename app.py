import streamlit as st
from settlement import (
    parse_settlement_table,
    build_verified_totals,
    generate_csv_row,
    validate,
)

st.set_page_config(page_title="Settlement Verifier", page_icon="🏇", layout="wide")

st.title("Settlement Verifier")
st.caption("Deterministic arithmetic for horse racing settlements. No AI in the arithmetic path.")

# --- Inputs ---
st.subheader("1. Meeting Details (For the Ledger)")
c1, c2, c3 = st.columns(3)
with c1:
    engine = st.text_input("Engine (C8/T1/G1/A1)", value="G1")
with c2:
    meeting = st.text_input("Course(s)", value="")
with c3:
    date = st.text_input("Date", value="")
    
notes_input = st.text_input("Notes (Optional)", value="")

st.subheader("2. Settlement Table")
input_text = st.text_area(
    "Paste the §28.1 Settlement Table",
    height=300,
    placeholder="Paste the full settlement table from the audit AI here..."
)

run = st.button("Verify", type="primary")

# --- Processing ---
if run and input_text.strip():
    rows, warnings = parse_settlement_table(input_text)
    errors = validate(rows)

    if errors:
        st.error(f"Cannot verify — {len(errors)} issue(s) found. Fix these in the input and re-run.")
        for e in errors:
            st.write(f"- {e}")
        st.stop()

    if warnings:
        with st.expander(f"{len(warnings)} warning(s) — non-fatal"):
            for w in warnings:
                st.write(f"- {w}")

    st.subheader("Parsed Rows")
    st.dataframe(
        [
            {
                "Race": r.race_id,
                "Tier": r.tier,
                "Horse": r.horse,
                "Declared": r.declared,
                "Result": r.result,
                "SP": r.sp,
                "Stake": f"£{r.stake:.2f}",
                "Return": f"£{r.return_amount:.2f}",
                "P/L": f"£{r.pnl:+.2f}",
            }
            for r in rows
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("3. Verified Totals")
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        verified = build_verified_totals(rows, meeting or "MEETING", date or "DATE")
        st.code(verified, language=None)

    with col_right:
        st.markdown("### 📋 Ledger CSV Row")
        st.markdown("Copy this line and paste it directly into Excel/Google Sheets.")
        csv_row = generate_csv_row(rows, meeting or "Meeting", date or "2026-01-01", engine or "ENGINE", notes_input)
        st.code(csv_row, language=None)

elif run:
    st.warning("Paste a settlement table first.")
