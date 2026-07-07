from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import uuid


class AccountType(models.TextChoices):
    ASSET = 'ASSET', 'Asset'
    LIABILITY = 'LIABILITY', 'Liability'
    EQUITY = 'EQUITY', 'Equity'
    REVENUE = 'REVENUE', 'Revenue'
    EXPENSE = 'EXPENSE', 'Expense'
    CONTRA = 'CONTRA', 'Contra Account'


class AccountSubType(models.TextChoices):
    # Assets
    CURRENT_ASSET = 'CURRENT_ASSET', 'Current Asset'
    FIXED_ASSET = 'FIXED_ASSET', 'Fixed Asset'
    BANK = 'BANK', 'Bank & Cash'
    ACCOUNTS_RECEIVABLE = 'AR', 'Accounts Receivable'
    PREPAID = 'PREPAID', 'Prepaid Expense'
    INVENTORY = 'INVENTORY', 'Inventory'
    # Liabilities
    CURRENT_LIABILITY = 'CURRENT_LIABILITY', 'Current Liability'
    LONG_TERM_LIABILITY = 'LONG_TERM', 'Long-term Liability'
    ACCOUNTS_PAYABLE = 'AP', 'Accounts Payable'
    TAX_PAYABLE = 'TAX_PAYABLE', 'Tax Payable'
    SALARY_PAYABLE = 'SALARY_PAYABLE', 'Salary Payable'
    # Equity
    RETAINED_EARNINGS = 'RETAINED', 'Retained Earnings'
    SHARE_CAPITAL = 'SHARE_CAPITAL', 'Share Capital'
    # Revenue
    OPERATING_REVENUE = 'OPERATING', 'Operating Revenue'
    OTHER_INCOME = 'OTHER_INCOME', 'Other Income'
    # Expenses
    OPERATING_EXPENSE = 'OPERATING_EXP', 'Operating Expense'
    DEPRECIATION = 'DEPRECIATION', 'Depreciation'
    SALARY_EXPENSE = 'SALARY_EXP', 'Salary Expense'
    TAX_EXPENSE = 'TAX_EXP', 'Tax Expense'


class ChartOfAccounts(models.Model):
    """
    Full Chart of Accounts following standard accounting principles.
    Account codes follow standard numbering:
    1xxx = Assets
    2xxx = Liabilities
    3xxx = Equity
    4xxx = Revenue
    5xxx = Expenses
    6xxx = Contra / Other
    """
    code = models.CharField(max_length=10, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    account_sub_type = models.CharField(
        max_length=30, choices=AccountSubType.choices
    )
    parent_account = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='sub_accounts'
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system_account = models.BooleanField(
        default=False,
        help_text="System accounts cannot be deleted"
    )
    normal_balance = models.CharField(
        max_length=6,
        choices=[('DEBIT', 'Debit'), ('CREDIT', 'Credit')],
        help_text="Normal balance side for this account type"
    )
    tax_applicable = models.BooleanField(default=False)
    bank_account = models.ForeignKey(
        'BankAccount', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='gl_account'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = "Chart of Account"
        verbose_name_plural = "Chart of Accounts"

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def balance(self):
        """Calculate current balance from journal entries."""
        from django.db.models import Sum
        debits = self.journal_lines.filter(
            journal__status='POSTED'
        ).aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
        credits = self.journal_lines.filter(
            journal__status='POSTED'
        ).aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

        if self.normal_balance == 'DEBIT':
            return debits - credits
        return credits - debits

    def get_balance_at_date(self, date):
        """Balance as of a specific date."""
        from django.db.models import Sum
        debits = self.journal_lines.filter(
            journal__status='POSTED',
            journal__posting_date__lte=date
        ).aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
        credits = self.journal_lines.filter(
            journal__status='POSTED',
            journal__posting_date__lte=date
        ).aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

        if self.normal_balance == 'DEBIT':
            return debits - credits
        return credits - debits

    def get_period_movements(self, start_date, end_date):
        """Get debit and credit movements for a period."""
        from django.db.models import Sum
        lines = self.journal_lines.filter(
            journal__status='POSTED',
            journal__posting_date__range=[start_date, end_date]
        )
        return {
            'debits': lines.aggregate(
                total=Sum('debit_amount')
            )['total'] or Decimal('0'),
            'credits': lines.aggregate(
                total=Sum('credit_amount')
            )['total'] or Decimal('0'),
        }


class BankAccount(models.Model):
    """Bank accounts linked to Chart of Accounts."""
    ACCOUNT_TYPES = [
        ('CURRENT', 'Current Account'),
        ('SAVINGS', 'Savings Account'),
        ('FIXED', 'Fixed Deposit'),
        ('PETTY_CASH', 'Petty Cash'),
    ]

    name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50, unique=True)
    branch = models.CharField(max_length=100, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    currency = models.CharField(max_length=3, default='TZS')
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    opening_balance_date = models.DateField()
    is_active = models.BooleanField(default=True)
    last_reconciled_date = models.DateField(null=True, blank=True)
    last_reconciled_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.bank_name} - {self.account_number})"

    @property
    def book_balance(self):
        """Current balance per books (GL)."""
        gl_account = self.gl_account.first()
        if gl_account:
            return gl_account.balance
        return Decimal('0')

    @property
    def unreconciled_count(self):
        return self.bank_transactions.filter(
            is_reconciled=False
        ).count()


class FiscalYear(models.Model):
    """Financial year for period-based reporting."""
    name = models.CharField(max_length=50)  # e.g., "FY 2024/2025"
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='closed_fiscal_years'
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()


class AccountingPeriod(models.Model):
    """Monthly accounting periods within a fiscal year."""
    fiscal_year = models.ForeignKey(
        FiscalYear, on_delete=models.CASCADE,
        related_name='periods'
    )
    name = models.CharField(max_length=50)  # e.g., "January 2025"
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return f"{self.fiscal_year.name} - {self.name}"


class JournalEntry(models.Model):
    """
    Double-entry journal entries - the core of the accounting system.
    Every financial transaction creates a balanced journal entry.
    """
    ENTRY_TYPES = [
        ('MANUAL', 'Manual Journal Entry'),
        ('PAYMENT', 'Payment Receipt'),
        ('EXPENSE', 'Expense'),
        ('PAYROLL', 'Payroll'),
        ('DEPRECIATION', 'Depreciation'),
        ('ADJUSTMENT', 'Adjustment'),
        ('OPENING', 'Opening Balance'),
        ('CLOSING', 'Period Closing'),
        ('BANK_RECON', 'Bank Reconciliation'),
        ('BILL', 'Bill Payment'),
        ('INVOICE', 'Invoice'),
        ('REVERSAL', 'Reversal Entry'),
    ]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_APPROVAL', 'Pending Approval'),
        ('POSTED', 'Posted'),
        ('REVERSED', 'Reversed'),
        ('VOID', 'Void'),
    ]

    reference = models.CharField(max_length=50, unique=True, db_index=True)
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    description = models.TextField()
    posting_date = models.DateField()
    period = models.ForeignKey(
        AccountingPeriod, on_delete=models.PROTECT,
        null=True, blank=True
    )
    fiscal_year = models.ForeignKey(
        FiscalYear, on_delete=models.PROTECT,
        null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT'
    )
    source_document = models.CharField(max_length=100, blank=True)
    source_module = models.CharField(max_length=50, blank=True)
    # Linked source objects
    content_type = models.ForeignKey(
        'contenttypes.ContentType',
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='journal_entries_created'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='journal_entries_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Reversal tracking
    reversed_by = models.OneToOneField(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reversal_of'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-posting_date', '-created_at']
        indexes = [
            models.Index(fields=['posting_date', 'status']),
            models.Index(fields=['entry_type', 'status']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.description[:50]}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    def _generate_reference(self):
        year = timezone.now().year
        count = JournalEntry.objects.filter(
            created_at__year=year
        ).count() + 1
        type_prefix = {
            'MANUAL': 'JNL',
            'PAYMENT': 'JNL-PAY',
            'EXPENSE': 'JNL-EXP',
            'PAYROLL': 'JNL-PAY',
            'DEPRECIATION': 'JNL-DEP',
            'BILL': 'JNL-BILL',
        }.get(self.entry_type, 'JNL')
        return f"{type_prefix}-{year}-{count:06d}"

    @property
    def total_debits(self):
        return self.lines.aggregate(
            total=models.Sum('debit_amount')
        )['total'] or Decimal('0')

    @property
    def total_credits(self):
        return self.lines.aggregate(
            total=models.Sum('credit_amount')
        )['total'] or Decimal('0')

    @property
    def is_balanced(self):
        return abs(self.total_debits - self.total_credits) < Decimal('0.01')

    def post(self, user):
        """Post a journal entry - marks it as permanent."""
        if not self.is_balanced:
            raise ValueError(
                f"Journal entry {self.reference} is not balanced. "
                f"Debits: {self.total_debits}, Credits: {self.total_credits}"
            )
        if self.status not in ['DRAFT', 'PENDING_APPROVAL']:
            raise ValueError(f"Cannot post entry with status {self.status}")

        self.status = 'POSTED'
        self.posted_at = timezone.now()
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save()

    def reverse(self, user, reversal_date=None, reason=""):
        """Create a reversing journal entry."""
        if self.status != 'POSTED':
            raise ValueError("Only posted entries can be reversed")

        reversal_date = reversal_date or timezone.now().date()
        reversal = JournalEntry.objects.create(
            entry_type='REVERSAL',
            description=f"REVERSAL of {self.reference}: {reason}",
            posting_date=reversal_date,
            status='DRAFT',
            source_document=self.reference,
            created_by=user,
            notes=f"Reversal of {self.reference}"
        )

        for line in self.lines.all():
            JournalEntryLine.objects.create(
                journal=reversal,
                account=line.account,
                description=f"Reversal: {line.description}",
                debit_amount=line.credit_amount,
                credit_amount=line.debit_amount,
            )

        self.reversed_by = reversal
        self.status = 'REVERSED'
        self.save()

        reversal.post(user)
        return reversal


class JournalEntryLine(models.Model):
    """Individual lines in a journal entry (debit or credit)."""
    journal = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE,
        related_name='lines'
    )
    account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='journal_lines'
    )
    description = models.CharField(max_length=300)
    debit_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    credit_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    # For bank reconciliation
    bank_transaction = models.ForeignKey(
        'BankTransaction', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='journal_lines'
    )
    cost_center = models.CharField(max_length=100, blank=True)
    tax_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        side = f"Dr {self.debit_amount}" if self.debit_amount else f"Cr {self.credit_amount}"
        return f"{self.account.code} - {side}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.debit_amount and self.credit_amount:
            raise ValidationError(
                "A journal line cannot have both debit and credit amounts"
            )
        if not self.debit_amount and not self.credit_amount:
            raise ValidationError(
                "A journal line must have either a debit or credit amount"
            )


class BankTransaction(models.Model):
    """
    Bank statement transactions for reconciliation.
    Imported from bank statements or webhooks.
    """
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit / Credit'),
        ('WITHDRAWAL', 'Withdrawal / Debit'),
        ('TRANSFER', 'Transfer'),
        ('CHARGE', 'Bank Charge'),
        ('INTEREST', 'Interest'),
        ('REVERSAL', 'Reversal'),
    ]

    STATUS_CHOICES = [
        ('UNMATCHED', 'Unmatched'),
        ('MATCHED', 'Matched'),
        ('RECONCILED', 'Reconciled'),
        ('EXCLUDED', 'Excluded'),
    ]

    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE,
        related_name='bank_transactions'
    )
    transaction_date = models.DateField()
    value_date = models.DateField(null=True, blank=True)
    description = models.TextField()
    reference = models.CharField(max_length=200, blank=True, db_index=True)
    transaction_type = models.CharField(
        max_length=20, choices=TRANSACTION_TYPES
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    # Positive = credit to bank account, Negative = debit
    running_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='UNMATCHED'
    )
    is_reconciled = models.BooleanField(default=False)
    reconciliation = models.ForeignKey(
        'BankReconciliation', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='transactions'
    )
    matched_journal_line = models.ForeignKey(
        JournalEntryLine, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='matched_bank_transactions'
    )
    # Source tracking
    source = models.CharField(
        max_length=20,
        choices=[
            ('WEBHOOK', 'Bank Webhook'),
            ('IMPORT', 'Manual Import'),
            ('MANUAL', 'Manual Entry'),
        ],
        default='MANUAL'
    )
    raw_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['bank_account', 'is_reconciled']),
            models.Index(fields=['transaction_date', 'bank_account']),
        ]

    def __str__(self):
        return (
            f"{self.transaction_date} | "
            f"{self.description[:40]} | "
            f"{self.amount:,.2f}"
        )


class BankReconciliation(models.Model):
    """
    Bank reconciliation statements.
    Matches book balance with bank statement balance.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('COMPLETED', 'Completed'),
        ('APPROVED', 'Approved'),
    ]

    reference = models.CharField(max_length=50, unique=True)
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT,
        related_name='reconciliations'
    )
    period_start = models.DateField()
    period_end = models.DateField()
    # Bank statement figures
    statement_opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2
    )
    statement_closing_balance = models.DecimalField(
        max_digits=15, decimal_places=2
    )
    # Book figures
    book_opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2
    )
    book_closing_balance = models.DecimalField(
        max_digits=15, decimal_places=2
    )
    # Reconciliation items
    deposits_in_transit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Deposits recorded in books but not yet on bank statement"
    )
    outstanding_checks = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Payments recorded in books but not yet cleared at bank"
    )
    bank_errors = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    book_errors = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    bank_charges_not_in_books = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    interest_not_in_books = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT'
    )
    notes = models.TextField(blank=True)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='reconciliations_prepared'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reconciliations_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_end']

    def __str__(self):
        return f"Recon {self.reference} - {self.bank_account.name} ({self.period_end})"

    def save(self, *args, **kwargs):
        if not self.reference:
            count = BankReconciliation.objects.count() + 1
            self.reference = f"RECON-{timezone.now().year}-{count:04d}"
        super().save(*args, **kwargs)

    @property
    def adjusted_bank_balance(self):
        """Bank balance adjusted for reconciling items."""
        return (
            self.statement_closing_balance
            + self.deposits_in_transit
            - self.outstanding_checks
            + self.bank_errors
        )

    @property
    def adjusted_book_balance(self):
        """Book balance adjusted for reconciling items."""
        return (
            self.book_closing_balance
            - self.bank_charges_not_in_books
            + self.interest_not_in_books
            + self.book_errors
        )

    @property
    def difference(self):
        return self.adjusted_bank_balance - self.adjusted_book_balance

    @property
    def is_reconciled(self):
        return abs(self.difference) < Decimal('0.01')


class Bill(models.Model):
    """
    Accounts Payable - Bills from vendors/suppliers.
    Tracks what the school owes to external parties.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
        ('DISPUTED', 'Disputed'),
    ]

    BILL_TYPES = [
        ('VENDOR', 'Vendor Invoice'),
        ('UTILITY', 'Utility Bill'),
        ('SALARY', 'Salary Payment'),
        ('RENT', 'Rent'),
        ('MAINTENANCE', 'Maintenance'),
        ('SUPPLIES', 'Supplies'),
        ('TAX', 'Tax Payment'),
        ('OTHER', 'Other'),
    ]

    reference = models.CharField(max_length=50, unique=True, db_index=True)
    bill_number = models.CharField(
        max_length=100, blank=True,
        help_text="Vendor's invoice number"
    )
    bill_type = models.CharField(max_length=20, choices=BILL_TYPES)
    vendor_name = models.CharField(max_length=200)
    vendor_contact = models.CharField(max_length=200, blank=True)
    vendor_tin = models.CharField(
        max_length=50, blank=True,
        help_text="Tax Identification Number"
    )
    # Dates
    bill_date = models.DateField()
    due_date = models.DateField()
    received_date = models.DateField(null=True, blank=True)
    # Amounts
    subtotal = models.DecimalField(max_digits=15, decimal_places=2)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )
    tax_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_paid = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    # Expense account
    expense_account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='bills',
        limit_choices_to={'account_type': 'EXPENSE'}
    )
    ap_account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='ap_bills',
        limit_choices_to={'account_sub_type': 'AP'},
        null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT'
    )
    description = models.TextField()
    attachment = models.FileField(
        upload_to='bills/attachments/', blank=True
    )
    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='bills_created'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='bills_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='bills'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-bill_date']
        indexes = [
            models.Index(fields=['status', 'due_date']),
            models.Index(fields=['vendor_name', 'status']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.vendor_name} ({self.total_amount:,.2f})"

    def save(self, *args, **kwargs):
        if not self.reference:
            count = Bill.objects.count() + 1
            self.reference = f"BILL-{timezone.now().year}-{count:05d}"
        self.tax_amount = self.subtotal * (self.tax_rate / 100)
        self.total_amount = self.subtotal + self.tax_amount
        super().save(*args, **kwargs)

    @property
    def balance_due(self):
        return self.total_amount - self.amount_paid

    @property
    def is_overdue(self):
        return (
            self.due_date < timezone.now().date()
            and self.status not in ['PAID', 'CANCELLED']
        )

    @property
    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0


class BillPayment(models.Model):
    """Payments made against bills."""
    reference = models.CharField(max_length=50, unique=True)
    bill = models.ForeignKey(
        Bill, on_delete=models.PROTECT,
        related_name='payments'
    )
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(
        max_length=30,
        choices=[
            ('BANK_TRANSFER', 'Bank Transfer'),
            ('CASH', 'Cash'),
            ('CHEQUE', 'Cheque'),
            ('MOBILE_MONEY', 'Mobile Money'),
        ]
    )
    bank_account = models.ForeignKey(
        BankAccount, null=True, blank=True,
        on_delete=models.SET_NULL
    )
    cheque_number = models.CharField(max_length=50, blank=True)
    bank_transaction = models.ForeignKey(
        BankTransaction, null=True, blank=True,
        on_delete=models.SET_NULL
    )
    journal_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True,
        on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            count = BillPayment.objects.count() + 1
            self.reference = f"BPMT-{timezone.now().year}-{count:05d}"
        super().save(*args, **kwargs)
        # Update bill amount paid and status
        self._update_bill_status()

    def _update_bill_status(self):
        bill = self.bill
        total_paid = bill.payments.aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')
        bill.amount_paid = total_paid
        if total_paid >= bill.total_amount:
            bill.status = 'PAID'
        elif total_paid > 0:
            bill.status = 'PARTIALLY_PAID'
        bill.save()


class FixedAsset(models.Model):
    """
    Fixed assets register for depreciation tracking.
    """
    ASSET_CATEGORIES = [
        ('BUILDING', 'Buildings'),
        ('FURNITURE', 'Furniture & Fittings'),
        ('EQUIPMENT', 'Equipment'),
        ('VEHICLE', 'Vehicles'),
        ('COMPUTER', 'Computers & Technology'),
        ('LAND', 'Land'),
        ('OTHER', 'Other'),
    ]

    DEPRECIATION_METHODS = [
        ('STRAIGHT_LINE', 'Straight Line'),
        ('REDUCING_BALANCE', 'Reducing Balance'),
        ('NONE', 'No Depreciation'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('DISPOSED', 'Disposed'),
        ('FULLY_DEPRECIATED', 'Fully Depreciated'),
        ('WRITTEN_OFF', 'Written Off'),
    ]

    asset_code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=ASSET_CATEGORIES)
    # Cost
    purchase_date = models.DateField()
    purchase_cost = models.DecimalField(max_digits=15, decimal_places=2)
    residual_value = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    # Depreciation
    depreciation_method = models.CharField(
        max_length=20, choices=DEPRECIATION_METHODS,
        default='STRAIGHT_LINE'
    )
    useful_life_years = models.IntegerField(default=5)
    depreciation_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Annual depreciation rate %"
    )
    accumulated_depreciation = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    # Accounts
    asset_account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='fixed_assets',
        limit_choices_to={'account_sub_type': 'FIXED_ASSET'}
    )
    depreciation_account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='depreciation_assets',
        limit_choices_to={'account_sub_type': 'DEPRECIATION'},
        null=True, blank=True
    )
    accumulated_dep_account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='accumulated_dep_assets',
        null=True, blank=True
    )
    # Status
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default='ACTIVE'
    )
    disposal_date = models.DateField(null=True, blank=True)
    disposal_amount = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    location = models.CharField(max_length=200, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['asset_code']

    def __str__(self):
        return f"{self.asset_code} - {self.name}"

    @property
    def net_book_value(self):
        return self.purchase_cost - self.accumulated_depreciation

    @property
    def annual_depreciation(self):
        if self.depreciation_method == 'STRAIGHT_LINE':
            return (
                self.purchase_cost - self.residual_value
            ) / self.useful_life_years
        elif self.depreciation_method == 'REDUCING_BALANCE':
            return self.net_book_value * (self.depreciation_rate / 100)
        return Decimal('0')

    @property
    def monthly_depreciation(self):
        return self.annual_depreciation / 12


class DepreciationSchedule(models.Model):
    """Monthly depreciation entries for fixed assets."""
    asset = models.ForeignKey(
        FixedAsset, on_delete=models.CASCADE,
        related_name='depreciation_schedule'
    )
    period = models.ForeignKey(
        AccountingPeriod, on_delete=models.PROTECT
    )
    depreciation_amount = models.DecimalField(max_digits=15, decimal_places=2)
    accumulated_depreciation = models.DecimalField(
        max_digits=15, decimal_places=2
    )
    net_book_value = models.DecimalField(max_digits=15, decimal_places=2)
    journal_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True,
        on_delete=models.SET_NULL
    )
    posted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['asset', 'period']


class BudgetLine(models.Model):
    """Budget vs actual tracking."""
    fiscal_year = models.ForeignKey(
        FiscalYear, on_delete=models.CASCADE,
        related_name='budget_lines'
    )
    account = models.ForeignKey(
        ChartOfAccounts, on_delete=models.PROTECT,
        related_name='budget_lines'
    )
    annual_budget = models.DecimalField(max_digits=15, decimal_places=2)
    # Monthly breakdown (JSON: {"1": amount, "2": amount, ...})
    monthly_budget = models.JSONField(default=dict)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['fiscal_year', 'account']

    @property
    def actual_to_date(self):
        return self.account.balance

    @property
    def variance(self):
        return self.annual_budget - self.actual_to_date

    @property
    def variance_percentage(self):
        if self.annual_budget == 0:
            return 0
        return (self.variance / self.annual_budget) * 100
