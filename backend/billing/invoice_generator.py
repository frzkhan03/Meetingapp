"""
Invoice PDF generation using ReportLab.
Generates professional PDF invoices with company branding.
"""
import io
import logging
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

from django.conf import settings

logger = logging.getLogger(__name__)

# Company information (PyTalk)
COMPANY_INFO = {
    'name': 'PyTalk',
    'tagline': 'Video Conferencing Platform',
    'address_line1': 'PyTalk Technologies',
    'address_line2': '',
    'city': '',
    'country': '',
    'email': 'billing@pytalk.io',
    'website': 'https://pytalk.veriright.com',
}


def generate_invoice_pdf(invoice):
    """
    Generate a PDF invoice and return the PDF bytes.

    Args:
        invoice: Invoice model instance

    Returns:
        bytes: PDF file content
    """
    buffer = io.BytesIO()

    # Create PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    # Get styles
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#6366f1'),
        spaceAfter=12,
    )

    company_style = ParagraphStyle(
        'Company',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        leading=14,
    )

    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=colors.HexColor('#374151'),
        spaceBefore=16,
        spaceAfter=8,
    )

    normal_style = ParagraphStyle(
        'NormalText',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#374151'),
        leading=14,
    )

    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#64748b'),
    )

    value_style = ParagraphStyle(
        'Value',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#1f2937'),
    )

    total_style = ParagraphStyle(
        'Total',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.HexColor('#6366f1'),
        fontName='Helvetica-Bold',
    )

    # Build document elements
    elements = []

    # Header with logo and company info
    header_data = [
        [
            Paragraph(f'<b>{COMPANY_INFO["name"]}</b>', title_style),
            Paragraph('<b>INVOICE</b>', ParagraphStyle(
                'InvoiceLabel',
                parent=styles['Normal'],
                fontSize=20,
                textColor=colors.HexColor('#374151'),
                alignment=TA_RIGHT,
            ))
        ],
        [
            Paragraph(COMPANY_INFO['tagline'], company_style),
            Paragraph(f'#{invoice.invoice_number}', ParagraphStyle(
                'InvoiceNumber',
                parent=styles['Normal'],
                fontSize=12,
                textColor=colors.HexColor('#6366f1'),
                alignment=TA_RIGHT,
                fontName='Helvetica-Bold',
            ))
        ],
    ]

    header_table = Table(header_data, colWidths=[100 * mm, 70 * mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10 * mm))

    # Invoice details and billing info
    issued_date_str = invoice.issued_date.strftime('%B %d, %Y') if invoice.issued_date else date.today().strftime('%B %d, %Y')
    due_date_str = invoice.due_date.strftime('%B %d, %Y') if invoice.due_date else 'Upon Receipt'

    # Status badge color
    status_color = '#22c55e' if invoice.status == 'paid' else '#f59e0b' if invoice.status == 'issued' else '#64748b'

    left_info = f"""
    <b>Invoice Date:</b> {issued_date_str}<br/>
    <b>Due Date:</b> {due_date_str}<br/>
    <b>Status:</b> <font color="{status_color}">{invoice.status.upper()}</font>
    """

    right_info = f"""
    <b>Bill To:</b><br/>
    {invoice.billing_name or invoice.organization.name}<br/>
    {invoice.billing_address.replace(chr(10), '<br/>') if invoice.billing_address else ''}<br/>
    """
    if invoice.tax_id:
        right_info += f'<b>{invoice.tax_type or "Tax ID"}:</b> {invoice.tax_id}<br/>'
    if invoice.billing_email:
        right_info += f'{invoice.billing_email}'

    info_data = [
        [
            Paragraph(left_info, normal_style),
            Paragraph(right_info, normal_style),
        ]
    ]

    info_table = Table(info_data, colWidths=[85 * mm, 85 * mm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12 * mm))

    # Line items table
    elements.append(Paragraph('Items', heading_style))

    # Table header
    from .currency import format_currency
    currency = invoice.currency.upper()

    line_items_data = [
        [
            Paragraph('<b>Description</b>', label_style),
            Paragraph('<b>Qty</b>', ParagraphStyle('LabelCenter', parent=label_style, alignment=TA_CENTER)),
            Paragraph('<b>Unit Price</b>', ParagraphStyle('LabelRight', parent=label_style, alignment=TA_RIGHT)),
            Paragraph('<b>Amount</b>', ParagraphStyle('LabelRight', parent=label_style, alignment=TA_RIGHT)),
        ]
    ]

    # Add line items
    for item in invoice.line_items:
        line_items_data.append([
            Paragraph(item.get('description', ''), normal_style),
            Paragraph(str(item.get('quantity', 1)), ParagraphStyle('ValueCenter', parent=value_style, alignment=TA_CENTER)),
            Paragraph(format_currency(item.get('unit_price', 0), currency), ParagraphStyle('ValueRight', parent=value_style, alignment=TA_RIGHT)),
            Paragraph(format_currency(item.get('amount', 0), currency), ParagraphStyle('ValueRight', parent=value_style, alignment=TA_RIGHT)),
        ])

    items_table = Table(line_items_data, colWidths=[90 * mm, 25 * mm, 30 * mm, 30 * mm])
    items_table.setStyle(TableStyle([
        # Header row styling
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        # All rows
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        # Lines
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#e5e7eb')),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.HexColor('#e5e7eb')),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 8 * mm))

    # Totals section
    totals_data = [
        [
            '',
            Paragraph('Subtotal:', ParagraphStyle('TotalLabel', parent=normal_style, alignment=TA_RIGHT)),
            Paragraph(format_currency(invoice.subtotal_cents, currency), ParagraphStyle('TotalValue', parent=value_style, alignment=TA_RIGHT)),
        ],
    ]

    if invoice.tax_amount_cents > 0:
        tax_label = f'Tax ({invoice.tax_type})' if invoice.tax_type else 'Tax'
        totals_data.append([
            '',
            Paragraph(f'{tax_label}:', ParagraphStyle('TotalLabel', parent=normal_style, alignment=TA_RIGHT)),
            Paragraph(format_currency(invoice.tax_amount_cents, currency), ParagraphStyle('TotalValue', parent=value_style, alignment=TA_RIGHT)),
        ])

    totals_data.append([
        '',
        Paragraph('<b>Total:</b>', ParagraphStyle('TotalLabel', parent=total_style, alignment=TA_RIGHT)),
        Paragraph(f'<b>{format_currency(invoice.total_cents, currency)}</b>', ParagraphStyle('TotalValue', parent=total_style, alignment=TA_RIGHT)),
    ])

    totals_table = Table(totals_data, colWidths=[90 * mm, 50 * mm, 35 * mm])
    totals_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        # Bold total row
        ('LINEABOVE', (1, -1), (-1, -1), 1, colors.HexColor('#6366f1')),
        ('TOPPADDING', (0, -1), (-1, -1), 10),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 15 * mm))

    # Payment status box
    if invoice.status == 'paid':
        paid_date_str = invoice.paid_date.strftime('%B %d, %Y') if invoice.paid_date else issued_date_str
        status_box = Table(
            [[Paragraph(f'<b>PAID</b> - Thank you for your payment on {paid_date_str}', ParagraphStyle(
                'StatusPaid',
                parent=styles['Normal'],
                fontSize=11,
                textColor=colors.HexColor('#166534'),
                alignment=TA_CENTER,
            ))]],
            colWidths=[170 * mm]
        )
        status_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#dcfce7')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 16),
            ('RIGHTPADDING', (0, 0), (-1, -1), 16),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#22c55e')),
        ]))
        elements.append(status_box)
        elements.append(Spacer(1, 10 * mm))

    # Notes
    if invoice.notes:
        elements.append(Paragraph('Notes', heading_style))
        elements.append(Paragraph(invoice.notes, normal_style))
        elements.append(Spacer(1, 10 * mm))

    # Footer
    footer_text = f"""
    <b>{COMPANY_INFO['name']}</b><br/>
    {COMPANY_INFO['email']} | {COMPANY_INFO['website']}<br/>
    <br/>
    <font size="8" color="#9ca3af">This invoice was generated automatically.
    For questions, contact {COMPANY_INFO['email']}</font>
    """
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(footer_text, ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#64748b'),
        alignment=TA_CENTER,
    )))

    # Build PDF
    doc.build(elements)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


def upload_invoice_to_s3(invoice, pdf_bytes):
    """
    Upload invoice PDF to S3 and return the URL.

    Args:
        invoice: Invoice model instance
        pdf_bytes: PDF file content

    Returns:
        str: S3 URL of the uploaded PDF
    """
    if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
        logger.warning('S3 credentials not configured, skipping invoice upload')
        return ''

    try:
        import boto3

        s3_key = f"invoices/{invoice.organization.id}/{invoice.invoice_number}.pdf"

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION,
        )

        s3_client.put_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key,
            Body=pdf_bytes,
            ContentType='application/pdf',
            ContentDisposition=f'inline; filename="{invoice.invoice_number}.pdf"',
        )

        # Build the public URL
        pdf_url = f"https://{settings.AWS_S3_BUCKET_NAME}.s3.{settings.AWS_S3_REGION}.amazonaws.com/{s3_key}"

        logger.info('Invoice PDF uploaded to S3: %s', pdf_url)
        return pdf_url

    except Exception as e:
        logger.exception('Failed to upload invoice PDF to S3: %s', e)
        return ''


def create_invoice_for_payment(payment, billing_info=None):
    """
    Create an Invoice record for a successful payment.

    Args:
        payment: Payment model instance
        billing_info: Optional BillingInfo model instance

    Returns:
        Invoice: The created Invoice instance
    """
    from .models import Invoice, BillingInfo
    from datetime import date

    subscription = payment.subscription
    organization = subscription.organization
    plan = subscription.plan

    # Get billing info if not provided
    if billing_info is None:
        try:
            billing_info = organization.billing_info
        except BillingInfo.DoesNotExist:
            billing_info = None

    # Create invoice
    invoice = Invoice(
        organization=organization,
        payment=payment,
        invoice_number=Invoice.generate_invoice_number(),
        currency=payment.currency.upper(),
        status='paid',
        issued_date=date.today(),
        paid_date=date.today(),
    )

    # Copy billing snapshot
    if billing_info:
        invoice.billing_name = billing_info.billing_name or organization.name
        invoice.billing_address = billing_info.get_formatted_address()
        invoice.billing_email = billing_info.billing_email
        invoice.tax_id = billing_info.tax_id
        invoice.tax_type = billing_info.tax_type
    else:
        invoice.billing_name = organization.name

    # Create line items
    billing_cycle = subscription.billing_cycle
    quantity = subscription.quantity or 1

    unit_price_cents = payment.amount_cents // quantity if quantity > 1 else payment.amount_cents

    line_item = {
        'description': f'{plan.name} Plan ({billing_cycle.title()})',
        'quantity': quantity,
        'unit_price': unit_price_cents,
        'amount': payment.amount_cents,
    }

    if plan.is_per_user and quantity > 1:
        line_item['description'] = f'{plan.name} Plan ({billing_cycle.title()}) - {quantity} users'

    invoice.line_items = [line_item]

    # Calculate totals (no tax calculated automatically - can be enhanced later)
    invoice.subtotal_cents = payment.amount_cents
    invoice.tax_amount_cents = 0  # Tax calculation can be added based on region
    invoice.total_cents = payment.amount_cents

    invoice.save()

    # Generate and upload PDF
    try:
        pdf_bytes = generate_invoice_pdf(invoice)
        pdf_url = upload_invoice_to_s3(invoice, pdf_bytes)
        if pdf_url:
            invoice.pdf_url = pdf_url
            invoice.save(update_fields=['pdf_url', 'updated_at'])

            # Also update the payment's invoice_pdf_url for backward compatibility
            payment.invoice_pdf_url = pdf_url
            payment.save(update_fields=['invoice_pdf_url'])
    except Exception as e:
        logger.exception('Failed to generate/upload invoice PDF: %s', e)

    return invoice
