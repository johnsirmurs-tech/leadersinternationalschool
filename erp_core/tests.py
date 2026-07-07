from django.test import TestCase, Client
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from erp_core.models import CustomUser, Role

# Monkeypatch store_rendered_templates to bypass Python 3.14 copy(context) bug in Django test suite
import django.test.client
django.test.client.store_rendered_templates = lambda *args, **kwargs: None

class AuthenticationTests(TestCase):
    def setUp(self):
        
        self.client = Client()
        
        # Create roles
        self.director_role = Role.objects.create(code='R01', name='Director')
        self.teacher_role = Role.objects.create(code='R06', name='Teacher')
        
        # Create a standard active user
        self.user = CustomUser.objects.create_user(
            username='teacher1',
            email='teacher1@leaders.ac.tz',
            password='Password123!',
            is_temporary_password=False
        )
        self.user.roles.add(self.teacher_role)

        # Create a user with temporary password
        self.temp_user = CustomUser.objects.create_user(
            username='new_staff',
            email='new_staff@leaders.ac.tz',
            password='TempPassword123!',
            is_temporary_password=True
        )
        self.temp_user.roles.add(self.teacher_role)

    def test_login_success(self):
        response = self.client.post(reverse('login'), {
            'username': 'teacher1',
            'password': 'Password123!'
        })
        self.assertEqual(response.status_code, 302)

    def test_temporary_password_redirect(self):
        # Authenticate and login
        response = self.client.post(reverse('login'), {
            'username': 'new_staff',
            'password': 'TempPassword123!'
        })
        self.assertEqual(response.status_code, 302)

    def test_login_lockout_after_five_failed_attempts(self):
        # Perform 5 failed login attempts
        for _ in range(5):
            self.client.post(reverse('login'), {
                'username': 'teacher1',
                'password': 'wrong_password'
            })
            
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertTrue(self.user.is_locked())

    def test_login_lockout_expires(self):
        # Lock user
        self.user.failed_login_attempts = 5
        # Set last failed login to 16 minutes ago
        self.user.last_failed_login = timezone.now() - timedelta(minutes=16)
        self.user.save()
        
        # User should not be locked anymore
        self.assertFalse(self.user.is_locked())
        
        # Login should succeed now
        response = self.client.post(reverse('login'), {
            'username': 'teacher1',
            'password': 'Password123!'
        })
        self.assertEqual(response.status_code, 302)

from erp_core.models import Section, Class, StudentProfile, FeeStructure, FeePayment, StaffSalaryConfig, StaffAllowance, StaffDeduction, Payroll, Payslip, PayslipLineItem, Expense

class FinancialTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.accountant_role = Role.objects.create(code='R03', name='Accountant')
        self.student_role = Role.objects.create(code='R07', name='Student')
        
        # Create accountant
        self.accountant = CustomUser.objects.create_user(
            username='accountant1',
            email='accountant1@leaders.ac.tz',
            password='Password123!',
            is_temporary_password=False
        )
        self.accountant.roles.add(self.accountant_role)

        # Create class and student
        self.section = Section.objects.create(name='Primary')
        self.class_obj = Class.objects.create(name='Grade 1 A', level_type='PRIMARY_LOWER', section=self.section)
        self.student_user = CustomUser.objects.create_user(
            username='student1',
            email='student1@leaders.ac.tz',
            password='Password123!',
            is_temporary_password=False
        )
        self.student_user.roles.add(self.student_role)
        self.student = StudentProfile.objects.create(
            user=self.student_user,
            student_id='STD-001',
            current_class=self.class_obj
        )

    def test_fee_structure_creation(self):
        self.client.force_login(self.accountant)
        response = self.client.post(reverse('fee_structure_setup'), {
            'class_ids': [self.class_obj.id],
            'vote_head': 'Tuition Fee',
            'amount': '1500000',
            'year': '2026',
            'billing_mode': 'TERMLY'
        })
        self.assertEqual(FeeStructure.objects.count(), 1)
        fs = FeeStructure.objects.first()
        self.assertEqual(fs.amount, 1500000)

    def test_fee_payment_and_balances(self):
        self.client.force_login(self.accountant)
        fs = FeeStructure.objects.create(
            class_obj=self.class_obj,
            vote_head='Tuition Fee',
            amount=1500000,
            year='2026',
            billing_mode='TERMLY'
        )

        response = self.client.post(reverse('record_payment'), {
            'student_id': self.student.id,
            'amount_paid': '500000',
            'payment_method': 'MOBILE',
            'allocation_mode': 'auto',
            'notes': 'Partial payment'
        })
        
        self.assertEqual(FeePayment.objects.count(), 1)
        payment = FeePayment.objects.first()
        self.assertEqual(payment.amount_paid, 500000)
        self.assertTrue(payment.receipt_number.startswith('REC-'))

        # Verify receipt page works
        receipt_response = self.client.get(reverse('view_receipt', kwargs={'receipt_no': payment.receipt_number}))
        self.assertEqual(receipt_response.status_code, 200)

    def test_payroll_generation_and_snapshot(self):
        self.client.force_login(self.accountant)
        
        # Configure staff salary
        cfg = StaffSalaryConfig.objects.create(
            staff=self.accountant,
            basic_pay=1200000,
            housing_allowance=200000,
            transport_allowance=100000,
            nssf_deduction=50000,
            paye_tax=100000
        )
        
        # Add itemized allowance
        allowance = StaffAllowance.objects.create(
            staff=self.accountant,
            name='Responsibility Allowance',
            amount=150000
        )

        # Generate payroll
        response = self.client.post(reverse('payroll_list'), {
            'action': 'generate',
            'month': '6',
            'year': '2026',
            'term': 'Term 2',
            'academic_year': '2026'
        })
        
        self.assertEqual(Payroll.objects.count(), 1)
        self.assertEqual(Payslip.objects.count(), 1)
        
        payslip = Payslip.objects.first()
        self.assertEqual(payslip.basic_pay, 1200000)
        # Check PayslipLineItem snapshot exists
        self.assertEqual(PayslipLineItem.objects.count(), 1)
        line_item = PayslipLineItem.objects.first()
        self.assertEqual(line_item.name, 'Responsibility Allowance')
        self.assertEqual(line_item.amount, 150000)

from erp_core.models import Subject, TeacherSubjectAssignment, StudentAttendance

class AcademicAndAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.director_role = Role.objects.create(code='R01', name='Director')
        self.teacher_role = Role.objects.create(code='R06', name='Teacher')
        self.student_role = Role.objects.create(code='R07', name='Student')

        self.director = CustomUser.objects.create_user(
            username='dir1', password='Password123!', email='dir1@leaders.ac.tz'
        )
        self.director.roles.add(self.director_role)

        self.teacher = CustomUser.objects.create_user(
            username='teach1', password='Password123!', email='teach1@leaders.ac.tz'
        )
        self.teacher.roles.add(self.teacher_role)

        self.section = Section.objects.create(name='Early Years')
        self.class_obj = Class.objects.create(
            name='Baby Class', section=self.section, level_type='EARLY_YEARS', class_teacher=self.teacher
        )

        self.student_user = CustomUser.objects.create_user(
            username='stud1', password='Password123!', email='stud1@leaders.ac.tz'
        )
        self.student_user.roles.add(self.student_role)
        self.student = StudentProfile.objects.create(
            user=self.student_user, student_id='ST-99', current_class=self.class_obj
        )

    def test_subject_setup_by_director(self):
        self.client.force_login(self.director)
        response = self.client.post(reverse('subject_setup'), {
            'name': 'Language Literacy',
            'level': 'EARLY_YEARS'
        })
        self.assertTrue(Subject.objects.filter(name='Language Literacy').exists())
        sub = Subject.objects.filter(name='Language Literacy').first()
        self.assertEqual(sub.level, 'EARLY_YEARS')

    def test_attendance_by_assigned_class_teacher(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('save_attendance'), {
            'class_id': self.class_obj.id,
            'date': '2026-06-27',
            f'status_{self.student.id}': 'PRESENT',
            f'remarks_{self.student.id}': 'On time'
        })
        self.assertEqual(StudentAttendance.objects.count(), 1)
        att = StudentAttendance.objects.first()
        self.assertEqual(att.status, 'PRESENT')

from erp_core.models import ParentProfile, BankDeposit, IntegrationConfig

class BankIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Roles
        self.accountant_role = Role.objects.create(code='R03', name='Accountant')
        self.parent_role = Role.objects.create(code='R08', name='Parent / Guardian')
        self.student_role = Role.objects.create(code='R07', name='Student')
        
        # Accountant
        self.accountant = CustomUser.objects.create_user(
            username='accountant2', password='Password123!', email='acct2@leaders.ac.tz'
        )
        self.accountant.roles.add(self.accountant_role)

        # Parent
        self.parent_user = CustomUser.objects.create_user(
            username='parent1', password='Password123!', email='parent1@mail.com', phone_number='255700000001'
        )
        self.parent_user.roles.add(self.parent_role)
        self.parent_profile = ParentProfile.objects.create(user=self.parent_user)

        # Section and Class
        self.section = Section.objects.create(name='Primary')
        self.class_obj = Class.objects.create(name='Class 2A', section=self.section)

        # Sibling 1
        self.student_user1 = CustomUser.objects.create_user(
            username='sibling1', password='Password123!', email='sib1@mail.com'
        )
        self.student_user1.roles.add(self.student_role)
        self.student1 = StudentProfile.objects.create(
            user=self.student_user1, student_id='LIS/STUD/2026/0001', current_class=self.class_obj
        )
        self.parent_profile.students.add(self.student1)

        # Sibling 2
        self.student_user2 = CustomUser.objects.create_user(
            username='sibling2', password='Password123!', email='sib2@mail.com'
        )
        self.student_user2.roles.add(self.student_role)
        self.student2 = StudentProfile.objects.create(
            user=self.student_user2, student_id='LIS/STUD/2026/0002', current_class=self.class_obj
        )
        self.parent_profile.students.add(self.student2)

        # Fee structures
        self.fee1 = FeeStructure.objects.create(
            class_obj=self.class_obj, vote_head='Tuition Fee', amount=50000.00, year='2026', billing_mode='TERMLY'
        )

    def test_bank_webhook_matches_student_and_parent(self):
        import json
        payload = {
            "ref": "LIS/STUD/2026/0001",
            "amount": "100000.00",
            "account_number": "0150243289000",
            "date": "2026-07-02T08:30:00Z",
            "sender_name": "Juma Hamisi",
            "transaction_id": "TXN-998877"
        }
        
        response = self.client.post(
            reverse('bank_deposit_webhook'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify db record
        self.assertEqual(BankDeposit.objects.count(), 1)
        deposit = BankDeposit.objects.first()
        self.assertEqual(deposit.ref_number, "TXN-998877")
        self.assertEqual(deposit.amount, 100000.00)
        self.assertEqual(deposit.bank_name, "CRDB")
        self.assertEqual(deposit.account_number, "0150243289000")
        self.assertEqual(deposit.sender_name, "Juma Hamisi")
        self.assertEqual(deposit.student, self.student1)
        self.assertEqual(deposit.parent, self.parent_profile)

    def test_allocate_bank_deposit_to_siblings(self):
        # Log a deposit
        deposit = BankDeposit.objects.create(
            ref_number="TXN-554433",
            student_ref="LIS/STUD/2026/0001",
            amount=80000.00,
            bank_name="EXIM",
            student=self.student1,
            parent=self.parent_profile
        )

        self.client.force_login(self.accountant)
        
        # Post allocation
        response = self.client.post(
            reverse('allocate_bank_deposit', args=[deposit.id]),
            {
                f'allocation_{self.student1.id}_{self.fee1.id}': '50000.00',
                f'allocation_{self.student2.id}_{self.fee1.id}': '30000.00'
            }
        )
        self.assertEqual(response.status_code, 302) # Redirects to list
        
        # Verify allocation state
        deposit.refresh_from_db()
        self.assertEqual(deposit.allocated_amount, 80000.00)
        self.assertTrue(deposit.is_fully_allocated)
        
        # Verify payments created
        self.assertEqual(FeePayment.objects.count(), 2)
        payment1 = FeePayment.objects.filter(student=self.student1).first()
        payment2 = FeePayment.objects.filter(student=self.student2).first()
        self.assertEqual(payment1.amount_paid, 50000.00)
        self.assertEqual(payment2.amount_paid, 30000.00)

    def test_integration_settings_save_by_director(self):
        # Create Director user
        director_role = Role.objects.get_or_create(code='R01', name='Director')[0]
        director = CustomUser.objects.create_user(
            username='director3', password='Password123!', email='dir3@leaders.ac.tz'
        )
        director.roles.add(director_role)
        self.client.force_login(director)

        # POST configuration changes
        response = self.client.post(
            reverse('integration_settings'),
            {
                'crdb_account': 'CRDB-TEST-99',
                'exim_account': 'EXIM-TEST-99',
                'pbz_account': 'PBZ-TEST-99',
                'whatsapp_provider': 'AFRICASTALKING',
                'whatsapp_api_url': 'https://api.africastalking.com/v1/sms',
                'whatsapp_api_key': 'SECRET_AT_KEY',
                'whatsapp_sender_number': 'LIS_RECEIPTS'
            }
        )
        self.assertEqual(response.status_code, 302)

        # Verify db config updated
        config = IntegrationConfig.get_solo()
        self.assertEqual(config.crdb_account, 'CRDB-TEST-99')
        self.assertEqual(config.whatsapp_provider, 'AFRICASTALKING')
        self.assertEqual(config.whatsapp_api_key, 'SECRET_AT_KEY')
        self.assertEqual(config.whatsapp_sender_number, 'LIS_RECEIPTS')

    def test_integration_settings_access_denied_to_non_director(self):
        # Login accountant (non-director)
        self.client.force_login(self.accountant)
        response = self.client.get(reverse('integration_settings'))
        self.assertEqual(response.status_code, 302) # Redirects (Access Denied)

    def test_retrospective_balance_calculation_excludes_future_terms(self):
        # Setup extra fee structures
        fee2 = FeeStructure.objects.create(
            class_obj=self.class_obj, vote_head='Activity Fee', amount=20000.00, year='2026', billing_mode='TERMLY', due_term='Term 2'
        )
        fee3 = FeeStructure.objects.create(
            class_obj=self.class_obj, vote_head='Graduation Fee', amount=40000.00, year='2026', billing_mode='TERMLY', due_term='Term 3'
        )
        
        # We login accountant
        self.client.force_login(self.accountant)
        
        # Request balances up to Term 2
        response = self.client.get(reverse('fee_balances'), {'term': 'Term 2', 'year': '2026'})
        self.assertEqual(response.status_code, 200)
        
        # Sibling 1 should have: self.fee1 (50000) + fee2 (20000) = 70000 total due. fee3 (40000) is excluded since it is Term 3!
        content = response.content.decode('utf-8')
        self.assertIn("TZS 70000.00", content)
        self.assertNotIn("TZS 110000.00", content)
        
    def test_fee_balances_whatsapp_reminders_individual_and_bulk(self):
        self.client.force_login(self.accountant)
        
        # Test individual reminder
        response = self.client.post(
            reverse('fee_balances') + "?term=Term 1&year=2026",
            {'action': 'send_whatsapp_individual', 'student_id': str(self.student1.id)}
        )
        self.assertEqual(response.status_code, 302)
        
        # Verify message logged to file or output printed
        import os
        from django.conf import settings
        log_path = os.path.join(settings.MEDIA_ROOT, 'whatsapp_logs.txt')
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("Balance Reminder", content)
        self.assertIn(self.student1.user.get_full_name(), content)
        
        # Test bulk reminder
        response = self.client.post(
            reverse('fee_balances') + "?term=Term 1&year=2026",
            {'action': 'send_whatsapp_bulk', 'student_ids': [str(self.student1.id), str(self.student2.id)]}
        )
        self.assertEqual(response.status_code, 302)



from erp_core.models_accounting import (
    ChartOfAccounts, BankAccount, FiscalYear, AccountingPeriod,
    JournalEntry, JournalEntryLine, Bill, BillPayment, FixedAsset,
    DepreciationSchedule, AccountType, AccountSubType
)
from erp_core.accounting_service import AccountingService, TrialBalanceService

class AccountingSystemTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.accountant_role, _ = Role.objects.get_or_create(code='R03', name='Accountant')
        self.director_role, _ = Role.objects.get_or_create(code='R01', name='Director')
        
        self.accountant = CustomUser.objects.create_user(
            username='accountant_test', email='acc_test@leaders.ac.tz', password='Password123!', is_temporary_password=False
        )
        self.accountant.roles.add(self.accountant_role)

        # Create fiscal year
        self.fiscal_year = FiscalYear.objects.create(
            name="FY 2026",
            start_date=timezone.now().date().replace(month=1, day=1),
            end_date=timezone.now().date().replace(month=12, day=31),
            is_active=True
        )

        # Create system accounts
        self.bank_acc = ChartOfAccounts.objects.create(
            code='1010', name='Bank Account', account_type=AccountType.ASSET,
            account_sub_type=AccountSubType.BANK, normal_balance='DEBIT', is_system_account=True
        )
        self.revenue_acc = ChartOfAccounts.objects.create(
            code='4010', name='Tuition Revenue', account_type=AccountType.REVENUE,
            account_sub_type=AccountSubType.OPERATING_REVENUE, normal_balance='CREDIT', is_system_account=True
        )
        self.salary_expense = ChartOfAccounts.objects.create(
            code='5010', name='Salary Expense', account_type=AccountType.EXPENSE,
            account_sub_type=AccountSubType.SALARY_EXPENSE, normal_balance='DEBIT', is_system_account=True
        )
        self.salary_payable = ChartOfAccounts.objects.create(
            code='2030', name='Salary Payable', account_type=AccountType.LIABILITY,
            account_sub_type=AccountSubType.SALARY_PAYABLE, normal_balance='CREDIT', is_system_account=True
        )
        self.operating_expense = ChartOfAccounts.objects.create(
            code='5020', name='Operating Expense', account_type=AccountType.EXPENSE,
            account_sub_type=AccountSubType.OPERATING_EXPENSE, normal_balance='DEBIT', is_system_account=True
        )

    def test_fee_payment_journal_posting(self):
        # Mock payment object
        from unittest.mock import MagicMock
        payment = MagicMock()
        payment.amount_paid = Decimal('1500000')
        payment.payment_date = timezone.now().date()
        payment.receipt_number = 'REC-2026-TEST'
        payment.student.user.get_full_name.return_value = 'Test Student'

        journal = AccountingService.record_fee_payment(payment, self.accountant)
        
        self.assertEqual(journal.status, 'POSTED')
        self.assertEqual(journal.lines.count(), 2)
        
        # Debits should equal credits
        self.assertEqual(journal.total_debits, Decimal('1500000'))
        self.assertEqual(journal.total_credits, Decimal('1500000'))
        
        # Verify balances
        self.assertEqual(self.bank_acc.balance, Decimal('1500000'))
        self.assertEqual(self.revenue_acc.balance, Decimal('1500000'))

    def test_payroll_journal_posting(self):
        # Mock payslip object
        from unittest.mock import MagicMock
        payslip = MagicMock()
        payslip.gross_earnings = Decimal('2000000')
        payslip.net_salary = Decimal('1700000')
        payslip.paye_tax = Decimal('200000')
        payslip.nssf_deduction = Decimal('100000')
        payslip.staff.get_full_name.return_value = 'Test Teacher'
        payslip.payroll.month = 6
        payslip.payroll.year = 2026

        journal = AccountingService.record_payroll(payslip, self.accountant)
        
        self.assertEqual(journal.status, 'POSTED')
        self.assertEqual(journal.lines.count(), 3)
        self.assertEqual(self.salary_expense.balance, Decimal('2000000'))
        self.assertEqual(self.salary_payable.balance, Decimal('1700000'))

    def test_financial_reports_trial_balance(self):
        # Record a manual balanced journal entry
        period = AccountingService.get_or_create_period(timezone.now().date())
        journal = JournalEntry.objects.create(
            entry_type='MANUAL', description='Office Supplies Purchase',
            posting_date=timezone.now().date(), period=period, created_by=self.accountant
        )
        # Dr Operating Expense
        JournalEntryLine.objects.create(
            journal=journal, account=self.operating_expense, description='Supplies', debit_amount=50000, credit_amount=0
        )
        # Cr Bank Account
        JournalEntryLine.objects.create(
            journal=journal, account=self.bank_acc, description='Paid Cash', debit_amount=0, credit_amount=50000
        )
        journal.post(self.accountant)

        tb = TrialBalanceService.get_trial_balance(timezone.now().date())
        self.assertEqual(tb['total_debits'], Decimal('50000'))
        self.assertEqual(tb['total_credits'], Decimal('50000'))


from erp_core.models_syllabus import (
    CambridgeStage, CambridgeSubject, SyllabusUnit, SyllabusTopic, SyllabusLearningObjective
)
from erp_core.models_quiz import (
    QuizBank, Quiz, QuizQuestion, QuizAttempt, StudentAnswer, AIGenerationJob
)
from erp_core.ai_quiz_service import QuizGenerationOrchestrator

class CambridgeQuizSystemTests(TestCase):
    def setUp(self):
        self.teacher_role, _ = Role.objects.get_or_create(code='R06', name='Teacher')
        self.student_role, _ = Role.objects.get_or_create(code='R07', name='Student')
        
        self.teacher = CustomUser.objects.create_user(
            username='teacher_quiz', email='t_quiz@leaders.ac.tz', password='Password123!', is_temporary_password=False
        )
        self.teacher.roles.add(self.teacher_role)
        
        self.student = CustomUser.objects.create_user(
            username='student_quiz', email='s_quiz@leaders.ac.tz', password='Password123!', is_temporary_password=False
        )
        self.student.roles.add(self.student_role)
        
        # Setup syllabus structure
        self.stage = CambridgeStage.objects.create(
            code='STG3', name='Cambridge Stage 3', stage_type='PRIMARY', stage_number=3
        )
        self.subject = CambridgeSubject.objects.create(
            code='MATH', name='Mathematics', subject_group='MATHEMATICS', syllabus_code='0845'
        )
        self.unit = SyllabusUnit.objects.create(
            subject=self.subject, stage=self.stage, unit_number=1, code='MATH-STG3-U1', title='Numbers'
        )
        self.topic = SyllabusTopic.objects.create(
            unit=self.unit, topic_number='1.1', title='Fractions', learning_objectives='Understand fractions as parts of a whole'
        )
        self.objective = SyllabusLearningObjective.objects.create(
            topic=self.topic, code='LO-MATH-F1', statement='Represent simple fractions'
        )

    def test_mock_quiz_generation_orchestrator(self):
        # Trigger mock quiz generation
        res = QuizGenerationOrchestrator.initiate_generation(
            user=self.teacher,
            subject_id=self.subject.id,
            stage_id=self.stage.id,
            topic_ids=[self.topic.id],
            difficulty='MEDIUM',
            num_questions=3,
            unit_id=self.unit.id
        )
        
        self.assertTrue(res['success'])
        self.assertEqual(res['questions_generated'], 3)
        self.assertEqual(QuizBank.objects.filter(status='AI_GENERATED').count(), 3)
        
        job = res['job']
        self.assertEqual(job.status, 'COMPLETED')
        self.assertEqual(job.generated_questions.count(), 3)

    def test_quiz_attempt_grading_engine(self):
        # Create a Quiz
        quiz = Quiz.objects.create(
            title='Fractions Math Quiz', subject=self.subject, stage=self.stage, unit=self.unit,
            total_questions=2, difficulty='MEDIUM', created_by=self.teacher, status='PUBLISHED'
        )
        quiz.topics.add(self.topic)
        
        q1 = QuizBank.objects.create(
            topic=self.topic, stage=self.stage, subject=self.subject, difficulty='MEDIUM',
            question_text='What is 1/2 of 10?', option_a='5', option_b='2', option_c='4', option_d='6',
            correct_answer='A', explanation='10 divided by 2 is 5', status='APPROVED', created_by=self.teacher
        )
        q2 = QuizBank.objects.create(
            topic=self.topic, stage=self.stage, subject=self.subject, difficulty='MEDIUM',
            question_text='What is 1/4 of 12?', option_a='2', option_b='3', option_c='4', option_d='5',
            correct_answer='B', explanation='12 divided by 4 is 3', status='APPROVED', created_by=self.teacher
        )
        
        qq1 = QuizQuestion.objects.create(quiz=quiz, question=q1, order=0, marks=2)
        qq2 = QuizQuestion.objects.create(quiz=quiz, question=q2, order=1, marks=3)
        
        attempt = QuizAttempt.objects.create(
            quiz=quiz, student=self.student, attempt_number=1, status='IN_PROGRESS',
            question_order=[str(q1.id), str(q2.id)]
        )
        
        # Student answers q1 correctly (A) and q2 incorrectly (C)
        StudentAnswer.objects.create(attempt=attempt, quiz_question=qq1, question=q1, selected_option='A')
        StudentAnswer.objects.create(attempt=attempt, quiz_question=qq2, question=q2, selected_option='C')
        
        score = attempt.calculate_score()
        
        # Total marks = 2 + 3 = 5. Obtained = 2. Percentage = 40.
        self.assertEqual(attempt.total_marks, 5)
        self.assertEqual(attempt.marks_obtained, 2)
        self.assertEqual(score, 40.0)
        self.assertFalse(attempt.passed)
        self.assertEqual(attempt.status, 'COMPLETED')
