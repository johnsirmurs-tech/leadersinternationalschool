from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, Q
from django.contrib.contenttypes.models import ContentType
from .models_accounting import (
    ChartOfAccounts, JournalEntry, JournalEntryLine,
    BankTransaction, AccountingPeriod, FiscalYear,
    AccountType, AccountSubType
)

class AccountingService:
    """
    Central service for all accounting operations.
    Ensures double-entry integrity for every transaction.
    """

    @staticmethod
    def get_or_create_period(date):
        """Get or create accounting period for a given date."""
        period = AccountingPeriod.objects.filter(
            start_date__lte=date,
            end_date__gte=date
        ).first()
        if not period:
            # Auto-create period if it doesn't exist
            import calendar
            year = date.year
            month = date.month
            last_day = calendar.monthrange(year, month)[1]
            fiscal_year = FiscalYear.objects.filter(
                start_date__lte=date,
                end_date__gte=date
            ).first()
            if not fiscal_year:
                # Create a default fiscal year if none matches
                start_f = date.replace(month=1, day=1)
                end_f = date.replace(month=12, day=31)
                fiscal_year, _ = FiscalYear.objects.get_or_create(
                    name=f"FY {date.year}",
                    defaults={
                        'start_date': start_f,
                        'end_date': end_f,
                        'is_active': True
                    }
                )
            period = AccountingPeriod.objects.create(
                fiscal_year=fiscal_year,
                name=date.strftime('%B %Y'),
                start_date=date.replace(day=1),
                end_date=date.replace(day=last_day)
            )
        return period

    @staticmethod
    def get_system_account(sub_type):
        """Retrieve a system account by subtype."""
        account = ChartOfAccounts.objects.filter(
            account_sub_type=sub_type,
            is_active=True
        ).first()
        if not account:
            # Create a default system account if it doesn't exist to prevent crashes
            code_prefix = {
                'BANK': '1010',
                'AR': '1020',
                'INVENTORY': '1030',
                'AP': '2010',
                'TAX_PAYABLE': '2020',
                'SALARY_PAYABLE': '2030',
                'RETAINED': '3010',
                'OPERATING': '4010',
                'SALARY_EXP': '5010',
                'OPERATING_EXP': '5020',
                'DEPRECIATION': '5030',
            }.get(sub_type, '9999')
            
            acc_type = AccountType.ASSET
            normal_bal = 'DEBIT'
            if code_prefix.startswith('2'):
                acc_type = AccountType.LIABILITY
                normal_bal = 'CREDIT'
            elif code_prefix.startswith('3'):
                acc_type = AccountType.EQUITY
                normal_bal = 'CREDIT'
            elif code_prefix.startswith('4'):
                acc_type = AccountType.REVENUE
                normal_bal = 'CREDIT'
            elif code_prefix.startswith('5'):
                acc_type = AccountType.EXPENSE
                normal_bal = 'DEBIT'

            account = ChartOfAccounts.objects.create(
                code=code_prefix,
                name=f"System {sub_type.replace('_', ' ').title()}",
                account_type=acc_type,
                account_sub_type=sub_type,
                normal_balance=normal_bal,
                is_system_account=True
            )
        return account

    @classmethod
    @transaction.atomic
    def record_fee_payment(cls, payment, user):
        """
        Create journal entry for student fee payment.
        Dr: Bank/Cash Account
        Cr: Tuition Revenue Account
        """
        bank_account = cls.get_system_account('BANK')
        revenue_account = cls.get_system_account('OPERATING')
        period = cls.get_or_create_period(payment.payment_date)

        journal = JournalEntry.objects.create(
            entry_type='PAYMENT',
            description=(
                f"Fee payment from {payment.student.user.get_full_name()} - "
                f"{payment.receipt_number}"
            ),
            posting_date=payment.payment_date,
            period=period,
            source_document=payment.receipt_number,
            source_module='fees',
            created_by=user,
            status='DRAFT'
        )

        # Dr Bank
        JournalEntryLine.objects.create(
            journal=journal,
            account=bank_account,
            description=f"Fee receipt from {payment.student.user.get_full_name()}",
            debit_amount=payment.amount_paid,
            credit_amount=Decimal('0')
        )
        # Cr Revenue
        JournalEntryLine.objects.create(
            journal=journal,
            account=revenue_account,
            description=f"Tuition fee - {payment.student.user.get_full_name()}",
            debit_amount=Decimal('0'),
            credit_amount=payment.amount_paid
        )

        journal.post(user)
        return journal

    @classmethod
    @transaction.atomic
    def record_payroll(cls, payslip, user):
        """
        Create journal entries for payroll per payslip.
        Dr: Salary Expense
        Cr: Salary Payable (or Bank if direct)
        Dr: Tax Payable (PAYE)
        """
        salary_expense = cls.get_system_account('SALARY_EXP')
        salary_payable = cls.get_system_account('SALARY_PAYABLE')
        tax_payable = cls.get_system_account('TAX_PAYABLE')
        
        # Determine date
        posting_date = timezone.now().date()
        period = cls.get_or_create_period(posting_date)

        journal = JournalEntry.objects.create(
            entry_type='PAYROLL',
            description=f"Payslip Finalization - {payslip.staff.get_full_name()} - {payslip.payroll.month}/{payslip.payroll.year}",
            posting_date=posting_date,
            period=period,
            source_document=f"SLIP-{payslip.id}",
            source_module='payroll',
            created_by=user,
            status='DRAFT'
        )

        # Dr Salary Expense (Gross Earnings)
        JournalEntryLine.objects.create(
            journal=journal,
            account=salary_expense,
            description=f"Gross earnings - {payslip.staff.get_full_name()}",
            debit_amount=payslip.gross_earnings,
            credit_amount=Decimal('0')
        )
        # Cr Salary Payable (Net Salary)
        JournalEntryLine.objects.create(
            journal=journal,
            account=salary_payable,
            description=f"Net salary payable - {payslip.staff.get_full_name()}",
            debit_amount=Decimal('0'),
            credit_amount=payslip.net_salary
        )
        # Cr Tax Payable (PAYE & ZSSF)
        total_tax = payslip.paye_tax + payslip.zssf_deduction
        if total_tax > 0:
            JournalEntryLine.objects.create(
                journal=journal,
                account=tax_payable,
                description=f"PAYE/ZSSF payable - {payslip.staff.get_full_name()}",
                debit_amount=Decimal('0'),
                credit_amount=total_tax
            )

        journal.post(user)
        return journal

    @classmethod
    @transaction.atomic
    def record_expense(cls, expense, user):
        """
        Record an expense transaction.
        Dr: Expense Account
        Cr: Bank/Cash
        """
        expense_account = cls.get_system_account('OPERATING_EXP')
        period = cls.get_or_create_period(expense.date)
        credit_account = cls.get_system_account('BANK')

        journal = JournalEntry.objects.create(
            entry_type='EXPENSE',
            description=f"Expense: {expense.description}",
            posting_date=expense.date,
            period=period,
            source_document=f"EXP-{expense.id}",
            source_module='expenses',
            created_by=user,
            status='DRAFT'
        )

        JournalEntryLine.objects.create(
            journal=journal,
            account=expense_account,
            description=expense.description,
            debit_amount=expense.amount,
            credit_amount=Decimal('0')
        )
        JournalEntryLine.objects.create(
            journal=journal,
            account=credit_account,
            description=f"Bank Credit - Expense payment",
            debit_amount=Decimal('0'),
            credit_amount=expense.amount
        )

        journal.post(user)
        return journal

    @classmethod
    @transaction.atomic
    def record_bill(cls, bill, user):
        """
        Record a vendor bill (accounts payable).
        Dr: Expense Account
        Cr: Accounts Payable
        """
        ap_account = bill.ap_account or cls.get_system_account('AP')
        period = cls.get_or_create_period(bill.bill_date)

        journal = JournalEntry.objects.create(
            entry_type='BILL',
            description=f"Bill from {bill.vendor_name}: {bill.description}",
            posting_date=bill.bill_date,
            period=period,
            source_document=bill.reference,
            source_module='bills',
            created_by=user,
            status='DRAFT'
        )

        # Dr Expense
        JournalEntryLine.objects.create(
            journal=journal,
            account=bill.expense_account,
            description=f"{bill.vendor_name}: {bill.description}",
            debit_amount=bill.subtotal,
            credit_amount=Decimal('0'),
            tax_amount=bill.tax_amount
        )

        # Cr Accounts Payable
        JournalEntryLine.objects.create(
            journal=journal,
            account=ap_account,
            description=f"AP: {bill.vendor_name} - {bill.reference}",
            debit_amount=Decimal('0'),
            credit_amount=bill.total_amount
        )

        journal.post(user)
        bill.journal_entry = journal
        bill.status = 'APPROVED'
        bill.approved_by = user
        bill.approved_at = timezone.now()
        bill.save()
        return journal

    @classmethod
    @transaction.atomic
    def record_bill_payment(cls, bill_payment, user):
        """
        Record payment against a bill.
        Dr: Accounts Payable
        Cr: Bank Account
        """
        ap_account = bill_payment.bill.ap_account or cls.get_system_account('AP')
        bank_account = cls.get_system_account('BANK')
        period = cls.get_or_create_period(bill_payment.payment_date)

        journal = JournalEntry.objects.create(
            entry_type='BILL',
            description=(
                f"Bill payment: {bill_payment.bill.reference} - "
                f"{bill_payment.bill.vendor_name}"
            ),
            posting_date=bill_payment.payment_date,
            period=period,
            source_document=bill_payment.reference,
            source_module='bills',
            created_by=user,
            status='DRAFT'
        )

        # Dr AP (reducing what we owe)
        JournalEntryLine.objects.create(
            journal=journal,
            account=ap_account,
            description=f"AP payment: {bill_payment.bill.vendor_name}",
            debit_amount=bill_payment.amount,
            credit_amount=Decimal('0')
        )
        # Cr Bank
        JournalEntryLine.objects.create(
            journal=journal,
            account=bank_account,
            description=f"Bank payment: {bill_payment.reference}",
            debit_amount=Decimal('0'),
            credit_amount=bill_payment.amount
        )

        journal.post(user)
        bill_payment.journal_entry = journal
        bill_payment.save()
        return journal


class TrialBalanceService:
    """Generate trial balance and financial statements."""

    @staticmethod
    def get_trial_balance(as_of_date=None, period=None):
        """
        Generate trial balance as of a date or for a period.
        Returns list of accounts with debit/credit balances.
        """
        as_of_date = as_of_date or timezone.now().date()
        accounts = ChartOfAccounts.objects.filter(is_active=True)

        trial_balance = []
        total_debits = Decimal('0')
        total_credits = Decimal('0')

        for account in accounts:
            lines = account.journal_lines.filter(journal__status='POSTED')
            if period:
                lines = lines.filter(journal__period=period)
            else:
                lines = lines.filter(journal__posting_date__lte=as_of_date)

            debits = lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            credits = lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

            if debits == 0 and credits == 0:
                continue

            if account.normal_balance == 'DEBIT':
                balance = debits - credits
                debit_bal = balance if balance > 0 else Decimal('0')
                credit_bal = abs(balance) if balance < 0 else Decimal('0')
            else:
                balance = credits - debits
                debit_bal = abs(balance) if balance < 0 else Decimal('0')
                credit_bal = balance if balance > 0 else Decimal('0')

            total_debits += debit_bal
            total_credits += credit_bal

            trial_balance.append({
                'account': account,
                'debit_balance': debit_bal,
                'credit_balance': credit_bal,
            })

        return {
            'lines': trial_balance,
            'total_debits': total_debits,
            'total_credits': total_credits,
        }

    @staticmethod
    def get_profit_and_loss(start_date, end_date):
        """Generate Profit & Loss (P&L) statement for a period."""
        accounts = ChartOfAccounts.objects.filter(is_active=True)
        revenue_lines = []
        expense_lines = []
        total_revenue = Decimal('0')
        total_expense = Decimal('0')

        for account in accounts:
            if account.account_type not in [AccountType.REVENUE, AccountType.EXPENSE]:
                continue

            lines = account.journal_lines.filter(
                journal__status='POSTED',
                journal__posting_date__range=[start_date, end_date]
            )

            debits = lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            credits = lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

            if debits == 0 and credits == 0:
                continue

            if account.normal_balance == 'DEBIT':
                balance = debits - credits
            else:
                balance = credits - debits

            if account.account_type == AccountType.REVENUE:
                total_revenue += balance
                revenue_lines.append({'account': account, 'balance': balance})
            else:
                total_expense += balance
                expense_lines.append({'account': account, 'balance': balance})

        net_profit = total_revenue - total_expense
        return {
            'revenue_lines': revenue_lines,
            'expense_lines': expense_lines,
            'total_revenue': total_revenue,
            'total_expense': total_expense,
            'net_profit': net_profit,
        }

    @staticmethod
    def get_balance_sheet(as_of_date):
        """Generate Balance Sheet as of a specific date."""
        accounts = ChartOfAccounts.objects.filter(is_active=True)
        asset_lines = []
        liability_lines = []
        equity_lines = []

        total_assets = Decimal('0')
        total_liabilities = Decimal('0')
        total_equity = Decimal('0')

        for account in accounts:
            if account.account_type not in [AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY]:
                continue

            balance = account.get_balance_at_date(as_of_date)
            if balance == 0:
                continue

            if account.account_type == AccountType.ASSET:
                total_assets += balance
                asset_lines.append({'account': account, 'balance': balance})
            elif account.account_type == AccountType.LIABILITY:
                total_liabilities += balance
                liability_lines.append({'account': account, 'balance': balance})
            elif account.account_type == AccountType.EQUITY:
                total_equity += balance
                equity_lines.append({'account': account, 'balance': balance})

        # Calculate Net Income to Date to roll into Retained Earnings
        # Profit = Revenue - Expenses up to as_of_date
        rev_debits = JournalEntryLine.objects.filter(
            journal__status='POSTED',
            journal__posting_date__lte=as_of_date,
            account__account_type=AccountType.REVENUE
        ).aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
        rev_credits = JournalEntryLine.objects.filter(
            journal__status='POSTED',
            journal__posting_date__lte=as_of_date,
            account__account_type=AccountType.REVENUE
        ).aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')
        total_rev = rev_credits - rev_debits

        exp_debits = JournalEntryLine.objects.filter(
            journal__status='POSTED',
            journal__posting_date__lte=as_of_date,
            account__account_type=AccountType.EXPENSE
        ).aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
        exp_credits = JournalEntryLine.objects.filter(
            journal__status='POSTED',
            journal__posting_date__lte=as_of_date,
            account__account_type=AccountType.EXPENSE
        ).aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')
        total_exp = exp_debits - exp_credits

        net_profit_retained = total_rev - total_exp
        total_equity += net_profit_retained
        equity_lines.append({
            'account': type('DummyAcc', (object,), {'name': 'Retained Earnings (Current Period)', 'code': '3999'}),
            'balance': net_profit_retained
        })

        return {
            'asset_lines': asset_lines,
            'liability_lines': liability_lines,
            'equity_lines': equity_lines,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'total_liabilities_and_equity': total_liabilities + total_equity,
        }
