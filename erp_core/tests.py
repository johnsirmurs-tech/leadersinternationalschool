from django.test import TestCase, Client
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
