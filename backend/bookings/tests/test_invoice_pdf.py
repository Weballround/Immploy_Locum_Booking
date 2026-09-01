from bookings.invoice_pdf import build_invoice_pdf


def test_invoice_pdf_paginates_long_line_sets():
    pdf = build_invoice_pdf([f"Invoice line {number}" for number in range(100)])

    assert b"/Count 2" in pdf
    assert b"(Invoice line 0) Tj" in pdf
    assert b"(Invoice line 99) Tj" in pdf
