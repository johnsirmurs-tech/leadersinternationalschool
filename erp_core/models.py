from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta

class Role(models.Model):
    ROLE_CHOICES = [
        ('R01', 'Director'),
        ('R02', 'Principal'),
        ('R03', 'Accountant'),
        ('R04', 'Head of Section'),
        ('R05', 'Dean'),
        ('R06', 'Teacher'),
        ('R07', 'Student'),
        ('R08', 'Parent / Guardian'),
    ]
    code = models.CharField(max_length=10, choices=ROLE_CHOICES, unique=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.code} - {self.name}"

class CustomUser(AbstractUser):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('SUSPENDED', 'Suspended'),
        ('REVOKED', 'Revoked'),
    ]
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    roles = models.ManyToManyField(Role, related_name='users', blank=True)
    
    # Password & Security details
    is_temporary_password = models.BooleanField(default=True)
    failed_login_attempts = models.IntegerField(default=0)
    last_failed_login = models.DateTimeField(blank=True, null=True)

    def is_locked(self):
        """Returns True if the user account is locked due to consecutive failed attempts (locked for 15 minutes)"""
        if self.failed_login_attempts >= 5:
            if self.last_failed_login:
                lock_expiration = self.last_failed_login + timedelta(minutes=15)
                if timezone.now() < lock_expiration:
                    return True
                else:
                    # Automatically unlock if 15 mins have passed
                    self.failed_login_attempts = 0
                    self.save()
        return False

    def get_lock_remaining_minutes(self):
        """Get remaining minutes for the lock to expire."""
        if self.last_failed_login:
            remaining = (self.last_failed_login + timedelta(minutes=15)) - timezone.now()
            minutes = int(remaining.total_seconds() / 60)
            return max(0, minutes)
        return 0

class Section(models.Model):
    name = models.CharField(max_length=100) # e.g. Early Childhood, Primary, Secondary
    head_of_section = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='headed_sections')

    def __str__(self):
        return self.name

class Class(models.Model):
    LEVEL_CHOICES = [
        ('EARLY_YEARS', 'Early Years'),
        ('PRIMARY_LOWER', 'Primary & Lower Secondary'),
        ('IGCSE', 'Upper Secondary / IGCSE'),
    ]
    name = models.CharField(max_length=100) # e.g. Baby Class, Middle Class, Pre-Unit, Class 1A
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='classes')
    class_teacher = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_classes')
    level_type = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='PRIMARY_LOWER')

    class Meta:
        verbose_name_plural = "Classes"

    def __str__(self):
        return f"{self.name} ({self.section.name})"

class Subject(models.Model):
    LEVEL_CHOICES = [
        ('EARLY_YEARS', 'Early Years (Learning Area)'),
        ('PRIMARY_LOWER', 'Primary & Lower Secondary'),
        ('IGCSE', 'Upper Secondary / IGCSE'),
    ]
    name = models.CharField(max_length=150)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='PRIMARY_LOWER')

    def __str__(self):
        return f"{self.name} ({self.get_level_display()})"

class TeacherSubjectAssignment(models.Model):
    teacher = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='subject_assignments')
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='teacher_assignments')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='teacher_assignments')

    class Meta:
        unique_together = ('teacher', 'class_obj', 'subject')

    def __str__(self):
        return f"{self.teacher.get_full_name()} - {self.class_obj.name} - {self.subject.name}"

class StudentAttendance(models.Model):
    STATUS_CHOICES = [
        ('PRESENT', 'Present'),
        ('ABSENT', 'Absent'),
        ('LATE', 'Late'),
    ]
    student = models.ForeignKey('StudentProfile', on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    remarks = models.CharField(max_length=200, blank=True, null=True)
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'date')

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.date}: {self.status}"

class StudentProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='student_profile')
    student_id = models.CharField(max_length=50, unique=True) # e.g. LIS/STUD/2026/0001
    current_class = models.ForeignKey(Class, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    enrollment_date = models.DateField(default=timezone.now)
    medical_conditions = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.student_id})"

class ParentProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='parent_profile')
    students = models.ManyToManyField(StudentProfile, related_name='parents')

    def __str__(self):
        return self.user.get_full_name()

class StaffProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='staff_profile')
    staff_id = models.CharField(max_length=50, unique=True) # e.g. LIS/STAFF/2026/0001
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_members')
    department = models.CharField(max_length=100, blank=True, null=True)
    date_joined = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.staff_id})"

class GradeBoundary(models.Model):
    FRAMEWORK_CHOICES = [
        ('A-G', 'Cambridge A-G'),
        ('1-9', 'Cambridge 1-9'),
    ]
    creator = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='created_boundaries')
    framework = models.CharField(max_length=10, choices=FRAMEWORK_CHOICES)
    grade_letter = models.CharField(max_length=5) # e.g. 'A', 'A*', '1', '9'
    min_percentage = models.IntegerField() # e.g. 80

    class Meta:
        verbose_name_plural = "Grade Boundaries"
        unique_together = ('framework', 'grade_letter')

    def __str__(self):
        return f"{self.framework}: {self.grade_letter} (>= {self.min_percentage}%)"

class LearningAreaProgress(models.Model):
    LEVEL_CHOICES = [
        ('EMERGING', 'Emerging (🟢)'),
        ('DEVELOPING', 'Developing (🟡)'),
        ('SECURE', 'Secure (🔵)'),
        ('EXCEEDING', 'Exceeding (⭐)'),
    ]
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='learning_progress')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='learning_progress_records', default=1)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    observation_text = models.TextField(blank=True, null=True)
    term = models.CharField(max_length=20)
    academic_year = models.CharField(max_length=20)
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.subject.name}: {self.level}"

class RawMark(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='raw_marks')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='raw_marks', default=1)
    term = models.CharField(max_length=20)
    academic_year = models.CharField(max_length=20)
    assessment_type = models.CharField(max_length=50)
    raw_score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2)
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=False)

    def get_percentage(self):
        if self.max_score > 0:
            return int((self.raw_score / self.max_score) * 100)
        return 0

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.subject.name} ({self.assessment_type}): {self.raw_score}/{self.max_score}"

class LessonPlan(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('APPROVED', 'Approved'),
        ('RETURNED', 'Returned'),
    ]
    PLAN_TYPE_CHOICES = [
        ('UPLOAD', 'Upload Document'),
        ('STRUCTURED', 'Structured Template'),
    ]
    teacher = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='lesson_plans')
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE)
    subject = models.CharField(max_length=100)
    date = models.DateField(default=timezone.now)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES, default='UPLOAD')
    
    # Uploaded plan fields
    file = models.FileField(upload_to='lesson_plans/', blank=True, null=True)
    
    # Structured fields for Cambridge Lesson Plan
    objectives = models.TextField(blank=True, null=True)
    materials = models.TextField(blank=True, null=True)
    activities = models.TextField(blank=True, null=True)
    evaluation = models.TextField(blank=True, null=True)
    
    # Review workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    comments = models.TextField(blank=True, null=True) # Reviewer written feedback
    reviewed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_plans')
    reviewed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.subject} - {self.class_obj.name} - Week {self.date}"

class AutoGradedActivity(models.Model):
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='activities')
    subject = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    due_date = models.DateTimeField()
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Auto Graded Activities"

    def __str__(self):
        return f"{self.title} - {self.subject} ({self.class_obj.name})"

class ActivityQuestion(models.Model):
    OPTION_CHOICES = [
        ('A', 'Option A'),
        ('B', 'Option B'),
        ('C', 'Option C'),
        ('D', 'Option D'),
    ]
    activity = models.ForeignKey(AutoGradedActivity, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    option_a = models.CharField(max_length=200)
    option_b = models.CharField(max_length=200)
    option_c = models.CharField(max_length=200)
    option_d = models.CharField(max_length=200)
    correct_option = models.CharField(max_length=2, choices=OPTION_CHOICES)

    def __str__(self):
        return self.question_text[:50]

class StudentActivitySubmission(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='activity_submissions')
    activity = models.ForeignKey(AutoGradedActivity, on_delete=models.CASCADE, related_name='submissions')
    score = models.DecimalField(max_digits=5, decimal_places=2) # Points achieved
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.activity.title}: {self.score}"

class FeeStructure(models.Model):
    BILLING_MODE_CHOICES = [
        ('YEARLY', 'Once a year'),
        ('TERMLY', 'Termly'),
        ('LIFETIME', 'One-time Lifetime Fee'),
    ]
    vote_head = models.CharField(max_length=150, default='Tuition Fee')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    year = models.CharField(max_length=20, default='2026')
    billing_mode = models.CharField(max_length=20, choices=BILLING_MODE_CHOICES, default='TERMLY')
    due_term = models.CharField(max_length=20, blank=True, null=True)
    is_one_time = models.BooleanField(default=False)
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='fee_structures')
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.class_obj.name} - {self.vote_head}: TZS {self.amount}"

class FeePayment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
        ('MOBILE', 'Mobile Money'),
        ('CHEQUE', 'Cheque'),
    ]
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='fee_payments')
    fee_structure = models.ForeignKey(FeeStructure, on_delete=models.CASCADE, related_name='payments')
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    receipt_number = models.CharField(max_length=100, unique=True)
    notes = models.TextField(blank=True, null=True)
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.receipt_number} - {self.student.user.get_full_name()}: TZS {self.amount_paid}"

class StaffSalaryConfig(models.Model):
    staff = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='salary_config')
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    nssf_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paye_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.staff.get_full_name()} Salary Configuration"

class StaffAllowance(models.Model):
    staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='allowances')
    name = models.CharField(max_length=100) # e.g. Responsibility Allowance
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.staff.get_full_name()} - {self.name}: {self.amount}"

class StaffDeduction(models.Model):
    staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='deductions')
    name = models.CharField(max_length=100) # e.g. Health Insurance
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.staff.get_full_name()} - {self.name}: {self.amount}"

class Payroll(models.Model):
    month = models.IntegerField()
    year = models.IntegerField()
    term = models.CharField(max_length=20, blank=True, null=True)
    academic_year = models.CharField(max_length=20, blank=True, null=True)
    is_finalized = models.BooleanField(default=False)
    finalized_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    finalized_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Payroll for {self.month}/{self.year}"

class Payslip(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('FINALIZED', 'Finalized'),
        ('PAID', 'Paid'),
    ]
    payroll = models.ForeignKey(Payroll, on_delete=models.CASCADE, related_name='payslips')
    staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='payslips')
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2)
    nssf_deduction = models.DecimalField(max_digits=12, decimal_places=2)
    paye_tax = models.DecimalField(max_digits=12, decimal_places=2)
    gross_earnings = models.DecimalField(max_digits=12, decimal_places=2)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    def __str__(self):
        return f"{self.staff.get_full_name()} Payslip - {self.payroll.month}/{self.payroll.year}"

class PayslipLineItem(models.Model):
    TYPE_CHOICES = [
        ('ALLOWANCE', 'Allowance'),
        ('DEDUCTION', 'Deduction'),
    ]
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='line_items')
    item_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.payslip.staff.get_full_name()} - {self.name}: {self.amount}"

class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('UTILITIES', 'Utilities'),
        ('SUPPLIES', 'Supplies'),
        ('MAINTENANCE', 'Maintenance'),
        ('TRANSPORT', 'Transport'),
        ('EVENTS', 'Events'),
        ('OTHER', 'Other'),
    ]
    date = models.DateField(default=timezone.now)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_to = models.CharField(max_length=150)
    payment_method = models.CharField(max_length=50) # Cash, Bank, Mobile, Cheque
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    receipt_file = models.FileField(upload_to='expenses/', blank=True, null=True)
    receipt_attached = models.BooleanField(default=False)
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} - {self.paid_to}: TZS {self.amount}"
