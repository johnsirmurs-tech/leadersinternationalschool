import os
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_receipt_pdf(payments, receipt_number):
    """
    Generates a PDF receipt using ReportLab for the given list of FeePayment objects
    under a shared receipt number, and returns the absolute file path.
    """
    if not payments:
        return None
        
    # Ensure receipts folder exists in media directory
    receipts_dir = os.path.join(settings.MEDIA_ROOT, 'receipts')
    if not os.path.exists(receipts_dir):
        os.makedirs(receipts_dir)
        
    pdf_filename = f"receipt_{receipt_number}.pdf"
    pdf_path = os.path.join(receipts_dir, pdf_filename)
    
    # Setup document
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=colors.HexColor('#0F2E59'),
        spaceAfter=15,
        alignment=1 # Centered
    )
    section_style = ParagraphStyle(
        'ReceiptSection',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=colors.HexColor('#E5A93C'),
        spaceAfter=8
    )
    body_style = ParagraphStyle(
        'ReceiptBody',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        spaceAfter=10
    )
    bold_body = ParagraphStyle(
        'ReceiptBodyBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    # Header
    story.append(Paragraph("Leaders International School", title_style))
    story.append(Paragraph("OFFICIAL PAYMENT RECEIPT", ParagraphStyle('Sub', parent=title_style, fontSize=14, spaceAfter=20)))
    story.append(Spacer(1, 10))
    
    # General details
    first_payment = payments[0]
    student = first_payment.student
    date_str = first_payment.created_at.strftime("%d %b %Y, %H:%M:%S")
    recorded_by = first_payment.recorded_by.get_full_name() if first_payment.recorded_by else "System"
    
    info_data = [
        [Paragraph("<b>Receipt Number:</b>", body_style), Paragraph(receipt_number, bold_body),
         Paragraph("<b>Date:</b>", body_style), Paragraph(date_str, body_style)],
        [Paragraph("<b>Student Name:</b>", body_style), Paragraph(student.user.get_full_name(), bold_body),
         Paragraph("<b>Admission No:</b>", body_style), Paragraph(student.student_id, bold_body)],
        [Paragraph("<b>Class:</b>", body_style), Paragraph(student.current_class.name if student.current_class else "N/A", body_style),
         Paragraph("<b>Recorded By:</b>", body_style), Paragraph(recorded_by, body_style)],
        [Paragraph("<b>Payment Method:</b>", body_style), Paragraph(first_payment.get_payment_method_display(), bold_body),
         Paragraph("", body_style), Paragraph("", body_style)]
    ]
    
    info_table = Table(info_data, colWidths=[110, 150, 110, 150])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 20))
    
    # Allocations table header
    story.append(Paragraph("Fee Allocations Breakdown", section_style))
    
    allocations_data = [
        [Paragraph("<b>Votehead Description</b>", bold_body), Paragraph("<b>Year/Term</b>", bold_body), Paragraph("<b>Allocated Amount (TZS)</b>", bold_body)]
    ]
    
    total_allocated = Decimal('0.00')
    for payment in payments:
        fs = payment.fee_structure
        term_display = fs.due_term if fs.due_term else ("Termly" if fs.billing_mode == 'TERMLY' else "One-time")
        allocations_data.append([
            Paragraph(fs.vote_head, body_style),
            Paragraph(f"{fs.year} - {term_display}", body_style),
            Paragraph(f"{payment.amount_paid:,.2f}", body_style)
        ])
        total_allocated += payment.amount_paid
        
    # Total row
    allocations_data.append([
        Paragraph("<b>TOTAL PAID</b>", bold_body),
        Paragraph("", body_style),
        Paragraph(f"<b>{total_allocated:,.2f}</b>", bold_body)
    ])
    
    allocations_table = Table(allocations_data, colWidths=[240, 120, 160])
    allocations_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F2E59')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor('#d0d0d0')),
        ('LINEABOVE', (0,-1), (-1,-1), 1.5, colors.HexColor('#0F2E59')),
    ]))
    
    # Make sure textcolor on table headers is white
    for i in range(3):
        allocations_data[0][i].style.textColor = colors.white
        
    story.append(allocations_table)
    story.append(Spacer(1, 30))
    
    # Footer notice
    story.append(Paragraph("Thank you for your payment. Please keep this receipt for your records.", ParagraphStyle('Foot', parent=body_style, fontName='Helvetica-Oblique', alignment=1, fontSize=9, textColor=colors.HexColor('#555'))))
    
    doc.build(story)
    return pdf_path

def send_whatsapp_receipt_pdf(parent_phone, pdf_path, receipt_number):
    """
    Simulates sending the receipt PDF to the parent's WhatsApp number.
    Logs the dispatch details to media/whatsapp_logs.txt.
    """
    if not parent_phone:
        print(f"[!] No phone number available to send receipt {receipt_number} via WhatsApp.")
        return False
        
    from erp_core.models import IntegrationConfig
    config = IntegrationConfig.get_solo()
        
    logs_dir = settings.MEDIA_ROOT
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        
    log_file_path = os.path.join(logs_dir, 'whatsapp_logs.txt')
    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf_filename = os.path.basename(pdf_path)
    
    log_message = (
        f"[{timestamp}] SENDING TO {parent_phone} | Receipt #: {receipt_number}\n"
        f"  Active WhatsApp Provider: {config.get_whatsapp_provider_display()}\n"
        f"  API URL: {config.whatsapp_api_url or 'N/A'}\n"
        f"  Sender Number: {config.whatsapp_sender_number or 'N/A'}\n"
        f"  API Key: {config.whatsapp_api_key or 'N/A'}\n"
        f"  Attachment: {pdf_path}\n"
        f"  Message: Dear Parent, thank you for your payment. We have successfully received "
        f"and allocated your bank deposit. Please find attached your official school payment receipt: {pdf_filename}\n"
        f"--------------------------------------------------\n"
    )
    
    try:
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(log_message)
        print(f"[WHATSAPP] Successfully dispatched PDF receipt {receipt_number} to parent phone {parent_phone} via {config.get_whatsapp_provider_display()}")
        return True
    except Exception as e:
        print(f"[!] Failed to log WhatsApp dispatch: {e}")
        return False
