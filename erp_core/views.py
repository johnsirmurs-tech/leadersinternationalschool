from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import CustomUser, Role, GradeBoundary, LearningAreaProgress, RawMark, LessonPlan, AutoGradedActivity, ActivityQuestion, StudentActivitySubmission, Class, StudentProfile, FeeStructure, FeePayment, StaffSalaryConfig, StaffAllowance, StaffDeduction, Payroll, Payslip, PayslipLineItem, Expense, Subject, TeacherSubjectAssignment, StudentAttendance, ParentProfile, StaffProfile, Section, StockItem, TransportRoute, StockMovement, BiometricDevice, BiometricLog, StaffAttendance, AttendanceException, BankDeposit, IntegrationConfig
from django.http import HttpResponse, JsonResponse
from .accounting_service import AccountingService, TrialBalanceService
from .models_accounting import (
    ChartOfAccounts, BankAccount, FiscalYear, AccountingPeriod,
    JournalEntry, JournalEntryLine, BankTransaction, BankReconciliation,
    Bill, BillPayment, FixedAsset, DepreciationSchedule, BudgetLine,
    AccountType, AccountSubType
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q, Count, Avg
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def custom_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username_or_email = request.POST.get('username', '').strip()
        password = request.POST.get('password')

        if not username_or_email or not password:
            messages.error(request, "Please enter both username/email and password.")
            return render(request, 'erp_core/login.html')

        # Find user by username or email (case-insensitive)
        user = None
        try:
            if '@' in username_or_email:
                user = CustomUser.objects.get(email__iexact=username_or_email)
            else:
                user = CustomUser.objects.get(username__iexact=username_or_email)
        except CustomUser.DoesNotExist:
            pass

        if user:
            # Check if locked
            if user.is_locked():
                remaining = user.get_lock_remaining_minutes()
                messages.error(request, f"This account is locked due to multiple failed login attempts. Please try again in {remaining} minutes.")
                return render(request, 'erp_core/login.html')

            if user.status != 'ACTIVE':
                messages.error(request, "Your account has been suspended or revoked. Please contact the school administration.")
                return render(request, 'erp_core/login.html')

            # Authenticate
            auth_user = authenticate(username=user.username, password=password)
            if auth_user is not None:
                # Reset failed attempts
                user.failed_login_attempts = 0
                user.save()

                login(request, auth_user)

                # Check if password is temporary
                if auth_user.is_temporary_password:
                    return redirect('change_temporary_password')

                return redirect('dashboard')
            else:
                # Failed attempt
                user.failed_login_attempts += 1
                user.last_failed_login = timezone.now()
                user.save()

                if user.failed_login_attempts >= 5:
                    messages.error(request, "Too many failed attempts. Your account has been locked for 15 minutes.")
                else:
                    attempts_left = 5 - user.failed_login_attempts
                    messages.error(request, f"Invalid password. You have {attempts_left} attempts remaining before account lock.")
        else:
            # Username/email not found
            messages.error(request, "Invalid username or email address.")

    return render(request, 'erp_core/login.html')

def custom_logout(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('login')

@login_required
def change_temporary_password(request):
    if not request.user.is_temporary_password:
        return redirect('dashboard')

    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'erp_core/change_password.html')

        try:
            # Validate password strength based on settings rules:
            # Minimum 8 characters, at least one uppercase, number, and special character.
            validate_password(new_password, user=request.user)

            # Manual extra check for uppercase, number, special character
            if not any(c.isupper() for c in new_password):
                raise ValidationError("Password must contain at least one uppercase letter.")
            if not any(c.isdigit() for c in new_password):
                raise ValidationError("Password must contain at least one number.")
            if not any(not c.isalnum() for c in new_password):
                raise ValidationError("Password must contain at least one special character.")

            # Save new password
            request.user.set_password(new_password)
            request.user.is_temporary_password = False
            request.user.save()
            
            # Keep user logged in after password change
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password updated successfully!")
            return redirect('dashboard')

        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)

    return render(request, 'erp_core/change_password.html')

@login_required
def dashboard(request):
    # If the user has a temporary password, force change
    if request.user.is_temporary_password:
        return redirect('change_temporary_password')

    from django.db import models
    user = request.user
    roles = user.roles.all()
    role_codes = [role.code for role in roles]
    
    context = {
        'roles': roles,
        'user': user
    }
    
    # Director (R01) or Principal (R02)
    if 'R01' in role_codes or 'R02' in role_codes:
        total_students = StudentProfile.objects.count()
        total_staff = StaffProfile.objects.count()
        fee_collected = FeePayment.objects.aggregate(total=models.Sum('amount_paid'))['total'] or 0
        
        # Calculate expected fees
        total_expected_fees = 0
        class_stats = Class.objects.annotate(student_count=models.Count('students'))
        for c in class_stats:
            if c.student_count > 0:
                class_fee_total = FeeStructure.objects.filter(class_obj=c).aggregate(total=models.Sum('amount'))['total'] or 0
                total_expected_fees += class_fee_total * c.student_count
        outstanding_fees = max(0, total_expected_fees - fee_collected)
        
        # Section breakdown
        today = timezone.now().date()
        sections = Section.objects.all()
        section_data = []
        for sec in sections:
            classes_in_sec = Class.objects.filter(section=sec)
            enrolled = StudentProfile.objects.filter(current_class__in=classes_in_sec).count()
            present = StudentAttendance.objects.filter(student__current_class__in=classes_in_sec, date=today, status='PRESENT').count()
            rate = (present / enrolled * 100) if enrolled > 0 else 0.0
            section_data.append({
                'name': sec.name,
                'enrolled': enrolled,
                'present': present,
                'rate': f"{rate:.1f}%" if enrolled > 0 else "0.0%"
            })

        # Calculate real student attendance rate
        total_enrolled = sum(sec['enrolled'] for sec in section_data)
        total_present = sum(sec['present'] for sec in section_data)
        student_attendance_rate = (total_present / total_enrolled * 100) if total_enrolled > 0 else 0.0

        # Calculate real staff attendance rate
        total_staff_count = StaffProfile.objects.count()
        present_staff_count = StaffAttendance.objects.filter(
            date=today, 
            status__in=['PRESENT', 'LATE']
        ).count()
        staff_attendance_rate = (present_staff_count / total_staff_count * 100) if total_staff_count > 0 else 0.0

        pending_plans_count = LessonPlan.objects.filter(status='SUBMITTED').count()
        
        # Format financial numbers for easy comprehension
        def format_currency(val):
            val_float = float(val)
            if val_float >= 1_000_000_000:
                return f"TZS {val_float / 1_000_000_000:.1f}B"
            elif val_float >= 1_000_000:
                return f"TZS {val_float / 1_000_000:.1f}M"
            else:
                return f"TZS {val_float:,.0f}"

        fee_collected_formatted = format_currency(fee_collected)
        outstanding_fees_formatted = format_currency(outstanding_fees)

        context.update({
            'total_students': total_students,
            'total_staff': total_staff,
            'fee_collected': fee_collected,
            'fee_collected_formatted': fee_collected_formatted,
            'outstanding_fees': outstanding_fees,
            'outstanding_fees_formatted': outstanding_fees_formatted,
            'student_attendance_rate': f"{student_attendance_rate:.1f}%" if isinstance(student_attendance_rate, float) else student_attendance_rate,
            'staff_attendance_rate': f"{staff_attendance_rate:.1f}%" if isinstance(staff_attendance_rate, float) else staff_attendance_rate,
            'section_data': section_data,
            'pending_plans_count': pending_plans_count,
        })
        
        if 'R01' in role_codes:
            return render(request, 'erp_core/dashboards/director.html', context)
        return render(request, 'erp_core/dashboards/principal.html', context)
        
    elif 'R03' in role_codes:
        return render(request, 'erp_core/dashboards/accountant.html', context)
        
    elif 'R04' in role_codes:
        sections_headed = user.headed_sections.all()
        classes_in_sections = Class.objects.filter(section__in=sections_headed)
        students_in_my_section = StudentProfile.objects.filter(current_class__in=classes_in_sections).count()
        context.update({
            'students_in_my_section': students_in_my_section
        })
        return render(request, 'erp_core/dashboards/head_of_section.html', context)
        
    elif 'R05' in role_codes:
        context.update({
            'open_discipline_cases': 0
        })
        return render(request, 'erp_core/dashboards/dean.html', context)
        
    elif 'R06' in role_codes:
        my_classes_count = TeacherSubjectAssignment.objects.filter(teacher=user).values('class_obj').distinct().count()
        attendance_today_exists = StudentAttendance.objects.filter(recorded_by=user, date=timezone.now().date()).exists()
        attendance_status = "Marked" if attendance_today_exists else "Not Marked"
        my_subjects_count = TeacherSubjectAssignment.objects.filter(teacher=user).values('subject').distinct().count()
        
        context.update({
            'my_classes_count': my_classes_count,
            'attendance_status': attendance_status,
            'my_subjects_count': my_subjects_count,
        })
        return render(request, 'erp_core/dashboards/teacher.html', context)
        
    elif 'R07' in role_codes:
        try:
            student_profile = user.student_profile
            student_class = student_profile.current_class
            if student_class:
                total_activities = AutoGradedActivity.objects.filter(class_obj=student_class).count()
                submitted_count = StudentActivitySubmission.objects.filter(student=student_profile).count()
                pending_homework = max(0, total_activities - submitted_count)
            else:
                pending_homework = 0
                
            total_attendance = StudentAttendance.objects.filter(student=student_profile).count()
            if total_attendance > 0:
                present_attendance = StudentAttendance.objects.filter(student=student_profile, status='PRESENT').count()
                attendance_rate = f"{(present_attendance / total_attendance) * 100:.1f}%"
            else:
                attendance_rate = "N/A"
        except StudentProfile.DoesNotExist:
            pending_homework = 0
            attendance_rate = "N/A"
            
        context.update({
            'pending_homework': pending_homework,
            'attendance_rate': attendance_rate,
        })
        return render(request, 'erp_core/dashboards/student.html', context)
        
    elif 'R08' in role_codes:
        total_outstanding = 0
        total_presents = 0
        total_records = 0
        children = []
        try:
            parent_profile = user.parent_profile
            children = parent_profile.students.all()
            for child in children:
                expected_fees = FeeStructure.objects.filter(class_obj=child.current_class).aggregate(total=models.Sum('amount'))['total'] or 0
                paid_fees = FeePayment.objects.filter(student=child).aggregate(total=models.Sum('amount_paid'))['total'] or 0
                total_outstanding += max(0, expected_fees - paid_fees)
                
                total_c = StudentAttendance.objects.filter(student=child).count()
                if total_c > 0:
                    present_c = StudentAttendance.objects.filter(student=child, status='PRESENT').count()
                    total_presents += present_c
                    total_records += total_c
        except ParentProfile.DoesNotExist:
            pass
            
        child_attendance_rate = f"{(total_presents / total_records) * 100:.1f}%" if total_records > 0 else "N/A"
        formatted_outstanding = f"TZS {total_outstanding:,.0f}" if total_outstanding > 0 else "TZS 0"
        
        context.update({
            'total_outstanding': formatted_outstanding,
            'child_attendance_rate': child_attendance_rate,
        })
        return render(request, 'erp_core/dashboards/parent.html', context)
        
    return render(request, 'erp_core/dashboards/default.html', context)

# ----------------- PHASE 2: ACADEMIC MODULE VIEWS -----------------

@login_required
def grade_boundaries(request):
    # Enforce Principal or Director only
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can configure grade boundaries.")
        return redirect('dashboard')

    boundaries = GradeBoundary.objects.all().order_by('framework', '-min_percentage')

    if request.method == 'POST':
        framework = request.POST.get('framework')
        grade_letter = request.POST.get('grade_letter')
        min_percentage = request.POST.get('min_percentage')

        if framework and grade_letter and min_percentage:
            try:
                # Get or create boundary
                boundary, created = GradeBoundary.objects.update_or_create(
                    framework=framework,
                    grade_letter=grade_letter,
                    defaults={'min_percentage': int(min_percentage), 'creator': request.user}
                )
                messages.success(request, f"Grade boundary for {grade_letter} ({framework}) successfully saved.")
            except Exception as e:
                messages.error(request, f"Error saving boundary: {str(e)}")
            return redirect('grade_boundaries')

    return render(request, 'erp_core/academics/grade_boundaries.html', {'boundaries': boundaries})

@login_required
def early_years_progress(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes:
        messages.error(request, "Only Teachers can access this entry panel.")
        return redirect('dashboard')

    user = request.user
    is_admin_or_dean = any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes)

    if is_admin_or_dean:
        classes = Class.objects.filter(level_type='EARLY_YEARS')
        learning_areas = Subject.objects.filter(level='EARLY_YEARS')
    else:
        assignments = TeacherSubjectAssignment.objects.filter(teacher=user, class_obj__level_type='EARLY_YEARS')
        classes = Class.objects.filter(id__in=assignments.values_list('class_obj_id', flat=True))
        learning_areas = Subject.objects.filter(id__in=assignments.values_list('subject_id', flat=True))

    selected_class_id = request.GET.get('class_id')
    selected_student_id = request.GET.get('student_id')
    
    selected_class = None
    selected_student = None
    students = []
    current_progress = {}

    if selected_class_id:
        selected_class = Class.objects.get(id=selected_class_id)
        students = StudentProfile.objects.filter(current_class=selected_class)
        
        if selected_student_id:
            selected_student = StudentProfile.objects.get(id=selected_student_id)
            progress_records = LearningAreaProgress.objects.filter(
                student=selected_student,
                term='Term 1',
                academic_year='2026'
            )
            for p in progress_records:
                current_progress[p.subject.id] = {
                    'level': p.level,
                    'observation_text': p.observation_text
                }

    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        term = request.POST.get('term', 'Term 1')
        academic_year = request.POST.get('academic_year', '2026')

        if student_id:
            student = StudentProfile.objects.get(id=student_id)
            for area in learning_areas:
                level = request.POST.get(f'level_{area.id}')
                observation_text = request.POST.get(f'obs_{area.id}')
                
                if level:
                    LearningAreaProgress.objects.update_or_create(
                        student=student,
                        subject=area,
                        term=term,
                        academic_year=academic_year,
                        defaults={
                            'level': level,
                            'observation_text': observation_text,
                            'recorded_by': request.user
                        }
                    )
            messages.success(request, f"All observations successfully saved for {student.user.get_full_name()}.")
            return redirect(f"{reverse('early_years_progress')}?class_id={selected_class_id}&student_id={selected_student_id}")

    return render(request, 'erp_core/academics/early_years_progress.html', {
        'classes': classes,
        'selected_class': selected_class,
        'selected_student': selected_student,
        'students': students,
        'learning_areas': learning_areas,
        'current_progress': current_progress,
    })

@login_required
def enter_raw_marks(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes:
        messages.error(request, "Only Teachers can enter marks.")
        return redirect('dashboard')

    user = request.user
    is_admin_or_dean = any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes)

    if is_admin_or_dean:
        classes = Class.objects.exclude(level_type='EARLY_YEARS')
        subjects = Subject.objects.exclude(level='EARLY_YEARS')
    else:
        assignments = TeacherSubjectAssignment.objects.filter(teacher=user).exclude(class_obj__level_type='EARLY_YEARS')
        classes = Class.objects.filter(id__in=assignments.values_list('class_obj_id', flat=True))
        subjects = Subject.objects.filter(id__in=assignments.values_list('subject_id', flat=True))
    
    selected_class_id = request.GET.get('class_id')
    selected_subject_id = request.GET.get('subject_id')
    assessment_type = request.GET.get('assessment_type')
    term = request.GET.get('term', 'Term 1')
    academic_year = request.GET.get('academic_year', '2026')

    selected_class = None
    selected_subject = None
    students = []
    existing_marks = {}
    is_locked = False

    if selected_class_id:
        selected_class = Class.objects.get(id=selected_class_id)
        students = StudentProfile.objects.filter(current_class=selected_class)

        if selected_subject_id and assessment_type:
            selected_subject = Subject.objects.get(id=selected_subject_id)
            marks = RawMark.objects.filter(
                student__current_class=selected_class,
                subject=selected_subject,
                assessment_type=assessment_type,
                term=term,
                academic_year=academic_year
            )
            is_locked = marks.filter(is_locked=True).exists()
            for m in marks:
                existing_marks[m.student.id] = m.raw_score

    return render(request, 'erp_core/academics/raw_marks_entry.html', {
        'classes': classes,
        'subjects': subjects,
        'selected_class': selected_class,
        'selected_subject': selected_subject,
        'students': students,
        'assessment_type': assessment_type,
        'term': term,
        'academic_year': academic_year,
        'existing_marks': existing_marks,
        'is_locked': is_locked,
    })

@login_required
def lesson_plan_list(request):
    user = request.user
    role_codes = [role.code for role in user.roles.all()]
    
    # Check if user is a reviewer (Director, Principal, Head of Section, Dean)
    is_reviewer = any(code in ['R01', 'R02', 'R04', 'R05'] for code in role_codes)
    
    if is_reviewer:
        plans = LessonPlan.objects.all().order_by('-date')
    else:
        plans = LessonPlan.objects.filter(teacher=user).order_by('-date')
        
    return render(request, 'erp_core/academics/lesson_plan_list.html', {
        'plans': plans,
        'is_reviewer': is_reviewer
    })

@login_required
def create_lesson_plan(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes:
        messages.error(request, "Only Teachers can build lesson plans.")
        return redirect('lesson_plan_list')

    classes = Class.objects.all()

    if request.method == 'POST':
        class_id = request.POST.get('class_id')
        subject = request.POST.get('subject')
        date = request.POST.get('date')
        plan_type = request.POST.get('plan_type')

        class_obj = Class.objects.get(id=class_id)

        plan = LessonPlan(
            teacher=request.user,
            class_obj=class_obj,
            subject=subject,
            date=date,
            plan_type=plan_type
        )

        if plan_type == 'UPLOAD':
            plan.file = request.FILES.get('file')
        else:
            plan.objectives = request.POST.get('objectives')
            plan.materials = request.POST.get('materials')
            plan.activities = request.POST.get('activities')
            plan.evaluation = request.POST.get('evaluation')

        plan.status = 'SUBMITTED'
        plan.save()

        messages.success(request, "Lesson plan submitted for review.")
        return redirect('lesson_plan_list')

    return render(request, 'erp_core/academics/lesson_plan_form.html', {
        'classes': classes,
    })

@login_required
def review_lesson_plan(request, plan_id):
    role_codes = [role.code for role in request.user.roles.all()]
    is_reviewer = any(code in ['R01', 'R02', 'R04', 'R05'] for code in role_codes)
    
    if not is_reviewer:
        messages.error(request, "Access denied.")
        return redirect('lesson_plan_list')

    plan = LessonPlan.objects.get(id=plan_id)

    if request.method == 'POST':
        action = request.POST.get('action') # APPROVE or RETURN
        comments = request.POST.get('comments')

        if action == 'APPROVE':
            plan.status = 'APPROVED'
        else:
            plan.status = 'RETURNED'

        plan.comments = comments
        plan.reviewed_by = request.user
        plan.reviewed_at = timezone.now()
        plan.save()
        messages.success(request, f"Lesson plan marked as {plan.get_status_display()}.")
        return redirect('lesson_plan_list')

    return render(request, 'erp_core/academics/lesson_plan_review.html', {'plan': plan})

@login_required
def download_lesson_plan_pdf(request, plan_id):
    plan = LessonPlan.objects.get(id=plan_id)
    
    # Create the HttpResponse object with PDF headers.
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="lesson_plan_{plan.id}.pdf"'

    # Simple canvas/ReportLab creation
    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=colors.HexColor('#0F2E59'),
        spaceAfter=15
    )
    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=colors.HexColor('#E5A93C'),
        spaceAfter=12
    )
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        spaceAfter=10
    )

    story.append(Paragraph(f"Leaders International School", title_style))
    story.append(Paragraph(f"Cambridge Lesson Plan - {plan.subject}", subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>Teacher:</b> {plan.teacher.get_full_name()}", body_style))
    story.append(Paragraph(f"<b>Class:</b> {plan.class_obj.name}", body_style))
    story.append(Paragraph(f"<b>Date:</b> {plan.date}", body_style))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>Objectives:</b>", subtitle_style))
    story.append(Paragraph(plan.objectives or "N/A", body_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Materials:</b>", subtitle_style))
    story.append(Paragraph(plan.materials or "N/A", body_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Activities:</b>", subtitle_style))
    story.append(Paragraph(plan.activities or "N/A", body_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Evaluation / Homework:</b>", subtitle_style))
    story.append(Paragraph(plan.evaluation or "N/A", body_style))

    doc.build(story)
    return response

@login_required
def activity_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    is_teacher = 'R06' in role_codes
    is_student = 'R07' in role_codes

    if is_teacher:
        activities = AutoGradedActivity.objects.filter(created_by=request.user)
    elif is_student:
        student_profile = request.user.student_profile
        activities = AutoGradedActivity.objects.filter(class_obj=student_profile.current_class)
    else:
        activities = AutoGradedActivity.objects.all()

    return render(request, 'erp_core/academics/activity_list.html', {
        'activities': activities,
        'is_teacher': is_teacher,
        'is_student': is_student
    })

@login_required
def create_activity(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes:
        messages.error(request, "Only Teachers can create activities.")
        return redirect('activity_list')

    classes = Class.objects.all()

    if request.method == 'POST':
        title = request.POST.get('title')
        class_id = request.POST.get('class_id')
        subject = request.POST.get('subject')
        due_date = request.POST.get('due_date')

        class_obj = Class.objects.get(id=class_id)
        activity = AutoGradedActivity.objects.create(
            class_obj=class_obj,
            subject=subject,
            title=title,
            due_date=due_date,
            created_by=request.user
        )

        # Process questions
        q_indices = request.POST.getlist('q_index')
        for idx in q_indices:
            q_text = request.POST.get(f'question_{idx}')
            opt_a = request.POST.get(f'opt_a_{idx}')
            opt_b = request.POST.get(f'opt_b_{idx}')
            opt_c = request.POST.get(f'opt_c_{idx}')
            opt_d = request.POST.get(f'opt_d_{idx}')
            correct = request.POST.get(f'correct_{idx}')

            if q_text and opt_a and correct:
                ActivityQuestion.objects.create(
                    activity=activity,
                    question_text=q_text,
                    option_a=opt_a,
                    option_b=opt_b,
                    option_c=opt_c,
                    option_d=opt_d,
                    correct_option=correct
                )

        messages.success(request, "Auto-graded MCQ activity created successfully.")
        return redirect('activity_list')

    return render(request, 'erp_core/academics/activity_create.html', {'classes': classes})

@login_required
def take_activity(request, activity_id):
    student_profile = request.user.student_profile
    activity = AutoGradedActivity.objects.get(id=activity_id)

    # Check if already submitted
    submission = StudentActivitySubmission.objects.filter(student=student_profile, activity=activity).first()
    if submission:
        messages.info(request, f"You have already completed this activity. Your score: {submission.score} points.")
        return redirect('activity_list')

    questions = activity.questions.all()

    if request.method == 'POST':
        correct_count = 0
        total_questions = questions.count()

        for q in questions:
            selected_answer = request.POST.get(f'q_{q.id}')
            if selected_answer == q.correct_option:
                correct_count += 1

        score = (correct_count / total_questions) * 100 if total_questions > 0 else 0
        
        # Save submission
        StudentActivitySubmission.objects.create(
            student=student_profile,
            activity=activity,
            score=score
        )
        
        messages.success(request, f"Activity submitted. You scored {correct_count}/{total_questions} ({score}%).")
        return redirect('activity_list')

    return render(request, 'erp_core/academics/activity_take.html', {
        'activity': activity,
        'questions': questions
    })

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@login_required
def auto_save_mark(request):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        subject_val = request.POST.get('subject')
        assessment_type = request.POST.get('assessment_type')
        raw_score = request.POST.get('raw_score')
        max_score = request.POST.get('max_score', '100')
        term = request.POST.get('term', 'Term 1')
        academic_year = request.POST.get('academic_year', '2026')

        if student_id and subject_val and assessment_type:
            try:
                student = StudentProfile.objects.get(id=student_id)
                if subject_val.isdigit():
                    subject_obj = Subject.objects.get(id=int(subject_val))
                else:
                    subject_obj = Subject.objects.get(name=subject_val)
                    
                is_cohort_locked = RawMark.objects.filter(
                    student__current_class=student.current_class,
                    subject=subject_obj,
                    assessment_type=assessment_type,
                    term=term,
                    academic_year=academic_year,
                    is_locked=True
                ).exists()
                
                if is_cohort_locked:
                    return JsonResponse({'status': 'error', 'message': 'Marks are locked and cannot be edited.'}, status=403)

                if raw_score == '' or raw_score is None:
                    RawMark.objects.filter(
                        student=student,
                        subject=subject_obj,
                        assessment_type=assessment_type,
                        term=term,
                        academic_year=academic_year
                    ).delete()
                else:
                    RawMark.objects.update_or_create(
                        student=student,
                        subject=subject_obj,
                        term=term,
                        academic_year=academic_year,
                        assessment_type=assessment_type,
                        defaults={
                            'raw_score': float(raw_score),
                            'max_score': float(max_score),
                            'recorded_by': request.user
                        }
                    )
                return JsonResponse({'status': 'success'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
def publish_and_lock_marks(request):
    if request.method == 'POST':
        class_id = request.POST.get('class_id')
        subject_val = request.POST.get('subject')
        assessment_type = request.POST.get('assessment_type')
        term = request.POST.get('term', 'Term 1')
        academic_year = request.POST.get('academic_year', '2026')

        role_codes = [role.code for role in request.user.roles.all()]
        if 'R06' not in role_codes:
            messages.error(request, "Only Teachers can publish marks.")
            return redirect('dashboard')

        if class_id and subject_val and assessment_type:
            class_obj = Class.objects.get(id=class_id)
            if subject_val.isdigit():
                subject_obj = Subject.objects.get(id=int(subject_val))
            else:
                subject_obj = Subject.objects.get(name=subject_val)
                
            marks = RawMark.objects.filter(
                student__current_class=class_obj,
                subject=subject_obj,
                assessment_type=assessment_type,
                term=term,
                academic_year=academic_year
            )
            
            if marks.exists():
                marks.update(is_locked=True)
                messages.success(request, f"Marks successfully published and locked for {class_obj.name}.")
            else:
                messages.warning(request, "No marks found to publish.")
                
            return redirect(f"{reverse('enter_raw_marks')}?class_id={class_id}&subject_id={subject_obj.id}&assessment_type={assessment_type}&term={term}&academic_year={academic_year}")

    return redirect('enter_raw_marks')

import random
from django.db.models import Sum

@login_required
def fee_structure_setup(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Only Accountant or Director can access fee setup.")
        return redirect('dashboard')

    classes = Class.objects.all()
    
    # Filtering logic
    filter_term = request.GET.get('term')
    filter_year = request.GET.get('year')
    filter_class = request.GET.get('class_id')
    
    fee_structures = FeeStructure.objects.all().order_by('class_obj', 'vote_head')
    
    if filter_term and filter_term != 'ALL':
        fee_structures = fee_structures.filter(due_term=filter_term)
    if filter_year:
        fee_structures = fee_structures.filter(year=filter_year)
    if filter_class:
        fee_structures = fee_structures.filter(class_obj_id=filter_class)

    if request.method == 'POST':
        class_ids = request.POST.getlist('class_ids')
        vote_head = request.POST.get('vote_head')
        amount = request.POST.get('amount')
        year = request.POST.get('year', '2026')
        billing_mode = request.POST.get('billing_mode', 'TERMLY')
        due_term = request.POST.get('due_term', '')
        is_one_time = request.POST.get('is_one_time') == 'on'
        description = request.POST.get('description', '')

        if class_ids and vote_head and amount:
            try:
                for cid in class_ids:
                    class_obj = Class.objects.get(id=cid)
                    FeeStructure.objects.update_or_create(
                        class_obj=class_obj,
                        vote_head=vote_head,
                        year=year,
                        billing_mode=billing_mode,
                        due_term=due_term if billing_mode == 'YEARLY' else None,
                        is_one_time=is_one_time,
                        defaults={
                            'amount': float(amount),
                            'description': description
                        }
                    )
                messages.success(request, f"Fee structure updated successfully for {len(class_ids)} classes.")
                return redirect('fee_structure_setup')
            except Exception as e:
                messages.error(request, f"Error saving fee structure: {str(e)}")

    return render(request, 'erp_core/financials/fee_structure.html', {
        'classes': classes,
        'fee_structures': fee_structures,
        'filter_term': filter_term,
        'filter_year': filter_year,
        'filter_class': filter_class,
    })

@login_required
def get_student_dues(request, student_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    try:
        student = StudentProfile.objects.get(id=student_id)
    except StudentProfile.DoesNotExist:
        return JsonResponse({'error': 'Student not found'}, status=404)

    term = request.GET.get('term', 'Term 1')
    year = request.GET.get('year', '2026')
    
    fee_structures = FeeStructure.objects.filter(class_obj=student.current_class)
    
    dues_list = []
    total_due = 0
    total_paid = 0
    
    for fs in fee_structures:
        paid = FeePayment.objects.filter(student=student, fee_structure=fs).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        due = fs.amount
        balance = due - paid
        total_due += due
        total_paid += paid
        
        # Check if current or arrear
        is_current = (fs.year == year) and (fs.billing_mode == 'TERMLY' or fs.is_one_time or fs.due_term == term)
        
        dues_list.append({
            'id': fs.id,
            'vote_head': fs.vote_head,
            'year': fs.year,
            'term': fs.due_term or ('Termly' if fs.billing_mode == 'TERMLY' else 'Lifetime'),
            'due': float(due),
            'paid': float(paid),
            'balance': float(balance),
            'is_current': is_current
        })
        
    return JsonResponse({
        'total_due': float(total_due),
        'already_paid': float(total_paid),
        'balance': float(total_due - total_paid),
        'items': dues_list
    })

@login_required
def record_payment(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes:
        messages.error(request, "Only Accountant can record payments.")
        return redirect('dashboard')

    classes = Class.objects.all()
    students = StudentProfile.objects.all()
    recent_payments = FeePayment.objects.all().order_by('-id')[:30]

    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        total_amount_paid_str = request.POST.get('amount_paid')
        payment_method = request.POST.get('payment_method')
        allocation_mode = request.POST.get('allocation_mode', 'auto')
        notes = request.POST.get('notes', '')

        if student_id and total_amount_paid_str:
            try:
                student = StudentProfile.objects.get(id=student_id)
                total_amount_paid = float(total_amount_paid_str)
                
                # Single receipt number for the entire payment
                rand_part = random.randint(1000, 9999)
                receipt_no = f"REC-{timezone.now().strftime('%Y%m%d')}-{rand_part}"

                # Check for manual allocations list
                allocations = []
                if allocation_mode == 'manual':
                    # Parse manual inputs: e.g. amount_fs_<id>
                    for key, val in request.POST.items():
                        if key.startswith('amount_fs_') and val:
                            fs_id = key.replace('amount_fs_', '')
                            allocations.append((fs_id, float(val)))
                else:
                    # Auto-allocation (Oldest first)
                    fee_structures = FeeStructure.objects.filter(class_obj=student.current_class).order_by('year', 'due_term', 'id')
                    remaining_payment = total_amount_paid
                    
                    for fs in fee_structures:
                        if remaining_payment <= 0:
                            break
                        paid = FeePayment.objects.filter(student=student, fee_structure=fs).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
                        due = fs.amount
                        balance = due - paid
                        if balance > 0:
                            allocate_amt = min(remaining_payment, float(balance))
                            allocations.append((fs.id, allocate_amt))
                            remaining_payment -= allocate_amt

                if not allocations and total_amount_paid > 0:
                    first_fs = FeeStructure.objects.filter(class_obj=student.current_class).first()
                    if first_fs:
                        allocations.append((first_fs.id, total_amount_paid))

                # Create payment objects for allocations
                for fs_id, amount in allocations:
                    if amount <= 0:
                        continue
                    fs = FeeStructure.objects.get(id=fs_id)
                    payment = FeePayment.objects.create(
                        student=student,
                        fee_structure=fs,
                        amount_paid=amount,
                        payment_method=payment_method,
                        receipt_number=receipt_no,
                        notes=notes,
                        recorded_by=request.user
                    )
                    AccountingService.record_fee_payment(payment, request.user)

                messages.success(request, f"Successfully recorded payment. Receipt {receipt_no} generated.")
                return redirect('view_receipt', receipt_no=receipt_no)
            except Exception as e:
                messages.error(request, f"Error saving payment: {str(e)}")

    return render(request, 'erp_core/financials/record_payment.html', {
        'classes': classes,
        'students': students,
        'recent_payments': recent_payments,
    })

@login_required
def view_receipt(request, receipt_no):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only Accountant, Director or Principal can view receipts.")
        return redirect('dashboard')
        
    payments = FeePayment.objects.filter(receipt_number=receipt_no)
    if not payments.exists():
        messages.error(request, "Receipt not found.")
        return redirect('record_payment')
        
    # Get common attributes
    first_payment = payments.first()
    student = first_payment.student
    payment_method = first_payment.get_payment_method_display()
    date = first_payment.created_at
    recorded_by = first_payment.recorded_by
    
    total_paid = sum(p.amount_paid for p in payments)
    
    # Calculate balance before and after this payment
    total_due = FeeStructure.objects.filter(class_obj=student.current_class).aggregate(Sum('amount'))['amount__sum'] or 0
    total_paid_ever = FeePayment.objects.filter(student=student, created_at__lte=date).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    balance_after = total_due - total_paid_ever
    balance_before = balance_after + total_paid
    
    return render(request, 'erp_core/financials/receipt.html', {
        'receipt_no': receipt_no,
        'date': date,
        'student': student,
        'payment_method': payment_method,
        'payments': payments,
        'total_paid': total_paid,
        'balance_before': balance_before,
        'balance_after': balance_after,
        'recorded_by': recorded_by,
    })

@login_required
def fee_balances(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "No permission to view fee balances.")
        return redirect('dashboard')

    # Get filter options
    classes = Class.objects.all()
    
    # Selected filters from request
    class_id = request.GET.get('class_id')
    min_balance_str = request.GET.get('min_balance')
    
    # Retrospective Term/Year logic
    today = timezone.now().date()
    current_year_str = str(today.year)
    current_month = today.month
    if current_month <= 4:
        default_term = 'Term 1'
    elif current_month <= 8:
        default_term = 'Term 2'
    else:
        default_term = 'Term 3'
        
    selected_term = request.GET.get('term', default_term)
    selected_year = request.GET.get('year', current_year_str)

    # Determine term index number
    import re
    from decimal import Decimal
    digits = re.findall(r'\d+', selected_term)
    selected_term_idx = int(digits[0]) if digits else 1

    # Base query for students
    students = StudentProfile.objects.all()
    if class_id:
        students = students.filter(current_class_id=class_id)

    student_balances = []

    for student in students:
        # Get fee structures applicable retrospectively
        fee_structures = FeeStructure.objects.filter(class_obj=student.current_class)
        retrospective_fees = []
        
        for fs in fee_structures:
            try:
                fs_year = int(fs.year)
                sel_year = int(selected_year)
            except ValueError:
                fs_year = 0
                sel_year = 0
                
            if fs_year < sel_year:
                retrospective_fees.append(fs)
            elif fs_year == sel_year:
                if fs.billing_mode == 'TERMLY' and fs.due_term:
                    fs_digits = re.findall(r'\d+', fs.due_term)
                    fs_term_idx = int(fs_digits[0]) if fs_digits else 1
                    if fs_term_idx <= selected_term_idx:
                        retrospective_fees.append(fs)
                else:
                    # Non-termly fees (yearly, lifetime) in the selected year
                    retrospective_fees.append(fs)
                    
        # Sum total dues retrospectively
        total_due = sum(fs.amount for fs in retrospective_fees)
        
        # Sum payments made by student to date
        total_paid = FeePayment.objects.filter(student=student).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        balance = Decimal(str(total_due)) - total_paid

        if balance <= 0:
            status = 'PAID'
        elif total_paid > 0:
            status = 'PARTIAL'
        else:
            status = 'UNPAID'

        row = {
            'student': student,
            'total_due': total_due,
            'total_paid': total_paid,
            'balance': balance,
            'status': status
        }
        
        # Apply min_balance filter
        if min_balance_str:
            try:
                min_bal = Decimal(min_balance_str)
                if balance < min_bal:
                    continue
            except ValueError:
                pass
                
        student_balances.append(row)

    # POST handling for WhatsApp alerts
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # Helper to log WhatsApp balance reminder
        def send_whatsapp_balance_reminder(parent_phone, student_name, balance_val, term_name):
            import os
            from django.conf import settings
            from .models import IntegrationConfig
            config = IntegrationConfig.get_solo()
            logs_dir = settings.MEDIA_ROOT
            if not os.path.exists(logs_dir):
                os.makedirs(logs_dir)
            log_file_path = os.path.join(logs_dir, 'whatsapp_logs.txt')
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_message = (
                f"[{timestamp}] SENDING TO {parent_phone} | Balance Reminder\n"
                f"  Active WhatsApp Provider: {config.get_whatsapp_provider_display()}\n"
                f"  Sender Number: {config.whatsapp_sender_number or 'N/A'}\n"
                f"  API Key: {config.whatsapp_api_key or 'N/A'}\n"
                f"  Message: Dear Parent, this is a friendly reminder that the outstanding school fees balance "
                f"for {student_name} is TZS {balance_val:,.2f} calculated up to {term_name}. Please settle the dues. Thank you.\n"
                f"--------------------------------------------------\n"
            )
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(log_message)
            print(f"[WHATSAPP] Successfully sent balance reminder for {student_name} to parent phone {parent_phone} via {config.get_whatsapp_provider_display()}")

        if action == 'send_whatsapp_individual':
            student_id = request.POST.get('student_id')
            student = StudentProfile.objects.get(id=student_id)
            parent = student.parents.first()
            parent_phone = parent.user.phone_number if parent else None
            
            # Recalculate balance for this student
            total_due = sum(
                fs.amount for fs in FeeStructure.objects.filter(class_obj=student.current_class)
                if int(fs.year) < int(selected_year) or 
                (int(fs.year) == int(selected_year) and 
                 (fs.billing_mode != 'TERMLY' or (fs.due_term and int((re.findall(r'\d+', fs.due_term) or [1])[0]) <= selected_term_idx)))
            )
            total_paid = FeePayment.objects.filter(student=student).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
            balance = Decimal(str(total_due)) - total_paid

            if parent_phone:
                send_whatsapp_balance_reminder(parent_phone, student.user.get_full_name(), balance, f"{selected_term} {selected_year}")
                messages.success(request, f"Balance reminder sent successfully via WhatsApp to parent of {student.user.get_full_name()}.")
            else:
                messages.error(request, f"Could not send reminder: No phone number configured for parent of {student.user.get_full_name()}.")
                
            return redirect(f"{reverse('fee_balances')}?{request.META.get('QUERY_STRING', '')}")

        elif action in ['send_reminder', 'send_whatsapp_bulk']:
            student_ids = request.POST.getlist('student_ids')
            sent_count = 0
            for sid in student_ids:
                student = StudentProfile.objects.get(id=sid)
                parent = student.parents.first()
                parent_phone = parent.user.phone_number if parent else None
                
                if parent_phone:
                    # Recalculate balance
                    total_due = sum(
                        fs.amount for fs in FeeStructure.objects.filter(class_obj=student.current_class)
                        if int(fs.year) < int(selected_year) or 
                        (int(fs.year) == int(selected_year) and 
                         (fs.billing_mode != 'TERMLY' or (fs.due_term and int((re.findall(r'\d+', fs.due_term) or [1])[0]) <= selected_term_idx)))
                    )
                    total_paid = FeePayment.objects.filter(student=student).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
                    balance = Decimal(str(total_due)) - total_paid
                    
                    send_whatsapp_balance_reminder(parent_phone, student.user.get_full_name(), balance, f"{selected_term} {selected_year}")
                    sent_count += 1
            
            if sent_count > 0:
                messages.success(request, f"Successfully sent WhatsApp balance reminders to {sent_count} parents.")
            else:
                messages.warning(request, "No reminders were sent (check parent phone configurations).")
                
            return redirect(f"{reverse('fee_balances')}?{request.META.get('QUERY_STRING', '')}")

    return render(request, 'erp_core/financials/fee_balances.html', {
        'student_balances': student_balances,
        'classes': classes,
        'selected_class_id': class_id,
        'min_balance': min_balance_str,
        'selected_term': selected_term,
        'selected_year': selected_year,
    })

@login_required
def salary_setup(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Only Accountant or Director can access salary configurations.")
        return redirect('dashboard')

    # Exclude students and parents
    staff_list_raw = CustomUser.objects.exclude(roles__code__in=['R07', 'R08']).distinct().prefetch_related('roles')
    staff_members = []
    for s in staff_list_raw:
        cfg, _ = StaffSalaryConfig.objects.get_or_create(
            staff=s,
            defaults={'basic_pay': 0}
        )
        roles = ", ".join([r.name for r in s.roles.all()])
        staff_members.append({
            'member': s,
            'roles': roles,
            'basic_pay': cfg.basic_pay,
            'housing': cfg.housing_allowance,
            'transport': cfg.transport_allowance,
            'zssf': cfg.zssf_deduction,
            'paye': cfg.paye_tax,
            'total_allowances': cfg.housing_allowance + cfg.transport_allowance,
            'total_deductions': cfg.zssf_deduction + cfg.paye_tax,
        })

    selected_staff_id = request.GET.get('staff_id')
    selected_staff = None
    salary_config = None
    allowances = []
    deductions = []

    if selected_staff_id:
        selected_staff = CustomUser.objects.get(id=selected_staff_id)
        salary_config, _ = StaffSalaryConfig.objects.get_or_create(
            staff=selected_staff,
            defaults={'basic_pay': 0}
        )
        allowances = StaffAllowance.objects.filter(staff=selected_staff)
        deductions = StaffDeduction.objects.filter(staff=selected_staff)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_config':
            basic_pay = request.POST.get('basic_pay')
            housing = request.POST.get('housing_allowance', 0)
            transport = request.POST.get('transport_allowance', 0)
            zssf = request.POST.get('zssf_deduction', 0)
            paye = request.POST.get('paye_tax', 0)

            salary_config.basic_pay = float(basic_pay)
            salary_config.housing_allowance = float(housing)
            salary_config.transport_allowance = float(transport)
            salary_config.zssf_deduction = float(zssf)
            salary_config.paye_tax = float(paye)
            salary_config.save()
            messages.success(request, f"Salary config updated for {selected_staff.get_full_name()}.")
            return redirect(f"{reverse('salary_setup')}?staff_id={selected_staff_id}")

        elif action == 'add_allowance':
            name = request.POST.get('allowance_name')
            amount = request.POST.get('allowance_amount')
            if name and amount:
                StaffAllowance.objects.create(
                    staff=selected_staff,
                    name=name,
                    amount=float(amount)
                )
                messages.success(request, f"Allowance '{name}' added.")
            return redirect(f"{reverse('salary_setup')}?staff_id={selected_staff_id}")

        elif action == 'add_deduction':
            name = request.POST.get('deduction_name')
            amount = request.POST.get('deduction_amount')
            if name and amount:
                StaffDeduction.objects.create(
                    staff=selected_staff,
                    name=name,
                    amount=float(amount)
                )
                messages.success(request, f"Deduction '{name}' added.")
            return redirect(f"{reverse('salary_setup')}?staff_id={selected_staff_id}")

    return render(request, 'erp_core/financials/salary_setup.html', {
        'staff_members': staff_members,
        'selected_staff': selected_staff,
        'salary_config': salary_config,
        'allowances': allowances,
        'deductions': deductions,
    })

@login_required
def payroll_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only Accountant, Director or Principal can access payroll.")
        return redirect('dashboard')

    payrolls = Payroll.objects.all().order_by('-year', '-month')

    if request.method == 'POST' and request.POST.get('action') == 'generate':
        if 'R03' not in role_codes and 'R01' not in role_codes:
            messages.error(request, "You do not have permission to generate payroll.")
            return redirect('payroll_list')
        month = int(request.POST.get('month'))
        year = int(request.POST.get('year'))
        term = request.POST.get('term', 'Term 1')
        academic_year = request.POST.get('academic_year', '2026')

        if not Payroll.objects.filter(month=month, year=year).exists():
            payroll = Payroll.objects.create(
                month=month,
                year=year,
                term=term,
                academic_year=academic_year
            )
            # Create payslips for all staff members
            staff_members = CustomUser.objects.exclude(roles__code__in=['R07', 'R08']).distinct()
            for s in staff_members:
                cfg, _ = StaffSalaryConfig.objects.get_or_create(staff=s, defaults={'basic_pay': 0})
                
                # Fetch custom allowances & deductions
                custom_allowances = StaffAllowance.objects.filter(staff=s)
                custom_deductions = StaffDeduction.objects.filter(staff=s)

                allowances_total = cfg.housing_allowance + cfg.transport_allowance + (custom_allowances.aggregate(Sum('amount'))['amount__sum'] or 0)
                deductions_total = cfg.zssf_deduction + cfg.paye_tax + (custom_deductions.aggregate(Sum('amount'))['amount__sum'] or 0)
                
                gross = cfg.basic_pay + cfg.housing_allowance + cfg.transport_allowance + (custom_allowances.aggregate(Sum('amount'))['amount__sum'] or 0)
                net = gross - deductions_total

                payslip = Payslip.objects.create(
                    payroll=payroll,
                    staff=s,
                    basic_pay=cfg.basic_pay,
                    housing_allowance=cfg.housing_allowance,
                    transport_allowance=cfg.transport_allowance,
                    zssf_deduction=cfg.zssf_deduction,
                    paye_tax=cfg.paye_tax,
                    gross_earnings=gross,
                    total_deductions=deductions_total,
                    net_salary=net,
                    status='PENDING'
                )

                # Store static snapshot items
                for allowance in custom_allowances:
                    PayslipLineItem.objects.create(
                        payslip=payslip,
                        item_type='ALLOWANCE',
                        name=allowance.name,
                        amount=allowance.amount
                    )
                for deduction in custom_deductions:
                    PayslipLineItem.objects.create(
                        payslip=payslip,
                        item_type='DEDUCTION',
                        name=deduction.name,
                        amount=deduction.amount
                    )

            messages.success(request, f"Payroll draft generated successfully for {month}/{year}.")
        else:
            messages.warning(request, "Payroll for this month/year already exists.")
        return redirect('payroll_list')

    is_accountant_or_director = 'R03' in role_codes or 'R01' in role_codes
    return render(request, 'erp_core/financials/payroll_list.html', {
        'payrolls': payrolls,
        'is_accountant_or_director': is_accountant_or_director
    })

@login_required
def finalize_payroll(request, payroll_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Only Accountant or Director can finalize payroll.")
        return redirect('dashboard')

    if request.method == 'POST':
        payroll = Payroll.objects.get(id=payroll_id)
        payroll.is_finalized = True
        payroll.finalized_by = request.user
        payroll.finalized_at = timezone.now()
        payroll.save()

        # Update payslip statuses and record in accounting
        pending_payslips = payroll.payslips.filter(status='PENDING')
        for payslip in pending_payslips:
            payslip.status = 'FINALIZED'
            payslip.save()
            AccountingService.record_payroll(payslip, request.user)

        messages.success(request, f"Payroll for {payroll.month}/{payroll.year} finalized. Notifications dispatched to staff.")
    return redirect('payroll_list')

@login_required
def view_payslip(request, payslip_id):
    payslip = Payslip.objects.get(id=payslip_id)
    
    # Restrict to own payslip or admin roles
    role_codes = [role.code for role in request.user.roles.all()]
    is_admin = 'R03' in role_codes or 'R01' in role_codes or 'R02' in role_codes
    if payslip.staff != request.user and not is_admin:
        messages.error(request, "You do not have permission to view this payslip.")
        return redirect('dashboard')

    allowance_items = payslip.line_items.filter(item_type='ALLOWANCE')
    deduction_items = payslip.line_items.filter(item_type='DEDUCTION')

    return render(request, 'erp_core/financials/payslip_detail.html', {
        'payslip': payslip,
        'allowance_items': allowance_items,
        'deduction_items': deduction_items,
    })

@login_required
def edit_payslip(request, payslip_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Only Accountant or Director can edit payslips.")
        return redirect('dashboard')

    payslip = Payslip.objects.get(id=payslip_id)
    if payslip.status != 'PENDING':
        messages.error(request, "Only pending payroll drafts can be edited.")
        return redirect('payroll_list')

    if request.method == 'POST':
        basic_pay = float(request.POST.get('basic_pay', 0))
        housing = float(request.POST.get('housing_allowance', 0))
        transport = float(request.POST.get('transport_allowance', 0))
        zssf = float(request.POST.get('zssf_deduction', 0))
        paye = float(request.POST.get('paye_tax', 0))

        # Re-fetch custom allowances and deductions sums
        custom_allowance_sum = payslip.line_items.filter(item_type='ALLOWANCE').exclude(name__in=['Basic Pay', 'Housing Allowance', 'Transport Allowance']).aggregate(Sum('amount'))['amount__sum'] or 0
        custom_deduction_sum = payslip.line_items.filter(item_type='DEDUCTION').exclude(name__in=['ZSSF Deduction', 'PAYE Tax']).aggregate(Sum('amount'))['amount__sum'] or 0

        gross = basic_pay + housing + transport + float(custom_allowance_sum)
        deductions_total = zssf + paye + float(custom_deduction_sum)
        net = gross - deductions_total

        payslip.basic_pay = basic_pay
        payslip.housing_allowance = housing
        payslip.transport_allowance = transport
        payslip.zssf_deduction = zssf
        payslip.paye_tax = paye
        payslip.gross_earnings = gross
        payslip.total_deductions = deductions_total
        payslip.net_salary = net
        payslip.save()

        messages.success(request, f"Payslip updated for {payslip.staff.get_full_name()}.")
        return redirect('payroll_list')

    return render(request, 'erp_core/financials/payslip_edit_modal.html', {
        'payslip': payslip,
    })

@login_required
def expense_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "No permission to view expenses.")
        return redirect('dashboard')

    expenses = Expense.objects.all().order_by('-date')
    total_amount = expenses.aggregate(Sum('amount'))['amount__sum'] or 0

    if request.method == 'POST':
        if 'R03' not in role_codes:
            messages.error(request, "Only Accountant can log expenses.")
            return redirect('expense_list')
        category = request.POST.get('category')
        description = request.POST.get('description')
        amount = request.POST.get('amount')
        paid_to = request.POST.get('paid_to')
        payment_method = request.POST.get('payment_method')
        reference_number = request.POST.get('reference_number', '')
        receipt_attached = request.POST.get('receipt_attached') == 'on'

        if category and amount and paid_to:
            try:
                expense = Expense.objects.create(
                    category=category,
                    description=description,
                    amount=float(amount),
                    paid_to=paid_to,
                    payment_method=payment_method,
                    reference_number=reference_number,
                    receipt_attached=receipt_attached,
                    recorded_by=request.user
                )
                AccountingService.record_expense(expense, request.user)
                messages.success(request, f"Expense recorded successfully: TZS {amount}")
                return redirect('expense_list')
            except Exception as e:
                messages.error(request, f"Error saving expense: {str(e)}")

    is_accountant = 'R03' in role_codes
    return render(request, 'erp_core/financials/expense_list.html', {
        'expenses': expenses,
        'total_amount': total_amount,
        'is_accountant': is_accountant,
    })


# ----------------- PHASE 4: USER ADMIN, ATTENDANCE, SUBJECTS, & REPORTS -----------------

from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Sum

# 1. User Management views
@login_required
def user_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can manage users.")
        return redirect('dashboard')

    query = request.GET.get('q', '')
    role_filter = request.GET.get('role', '')

    users = CustomUser.objects.all().order_by('username')

    if query:
        users = users.filter(
            models.Q(username__icontains=query) |
            models.Q(email__icontains=query) |
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query)
        )

    if role_filter:
        users = users.filter(roles__code=role_filter)

    roles = Role.objects.all()

    return render(request, 'erp_core/administration/user_list.html', {
        'users': users,
        'roles': roles,
        'q': query,
        'role_filter': role_filter,
    })

@login_required
def user_create(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can manage users.")
        return redirect('dashboard')

    roles = Role.objects.all()
    classes = Class.objects.all()

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        role_ids = request.POST.getlist('roles')
        is_temp = request.POST.get('is_temporary_password') == 'on'
        password = request.POST.get('password', 'Password123!')

        # Student specific
        class_id = request.POST.get('class_id')
        student_id = request.POST.get('student_id')

        # Staff specific
        staff_id = request.POST.get('staff_id')
        department = request.POST.get('department')

        if username and email:
            try:
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    password=password,
                    is_temporary_password=is_temp
                )
                for r_id in role_ids:
                    role = Role.objects.get(id=r_id)
                    user.roles.add(role)

                user_roles = [r.code for r in user.roles.all()]

                # Create profile based on roles
                if 'R07' in user_roles and class_id and student_id:
                    class_obj = Class.objects.get(id=class_id)
                    StudentProfile.objects.create(
                        user=user,
                        student_id=student_id,
                        current_class=class_obj
                    )
                elif any(c in ['R01', 'R02', 'R03', 'R04', 'R05', 'R06'] for c in user_roles) and staff_id:
                    StaffProfile.objects.create(
                        user=user,
                        staff_id=staff_id,
                        department=department
                    )

                messages.success(request, f"User {username} successfully created.")
                return redirect('user_list')
            except Exception as e:
                messages.error(request, f"Error creating user: {str(e)}")

    return render(request, 'erp_core/administration/user_form.html', {
        'roles': roles,
        'classes': classes,
        'is_create': True
    })

@login_required
def staff_enrollment(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can enroll staff.")
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        role_id = request.POST.get('role_id')
        staff_id = request.POST.get('staff_id')
        department = request.POST.get('department')
        education_level = request.POST.get('education_level')
        age = request.POST.get('age')
        employment_status = request.POST.get('employment_status')
        basic_pay = request.POST.get('basic_pay', 0)
        password = request.POST.get('password', 'Password123!')

        try:
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
                is_temporary_password=False
            )
            role = Role.objects.get(id=role_id)
            user.roles.add(role)

            # Create StaffProfile
            StaffProfile.objects.create(
                user=user,
                staff_id=staff_id,
                department=department,
                education_level=education_level,
                age=int(age) if age else None,
                employment_status=employment_status
            )

            # Create ZSSF config
            StaffSalaryConfig.objects.create(
                staff=user,
                basic_pay=float(basic_pay) if basic_pay else 0
            )

            messages.success(request, f"Staff member {first_name} {last_name} enrolled successfully.")
            return redirect('staff_enrollment')
        except Exception as e:
            messages.error(request, f"Error enrolling staff: {str(e)}")

    # Automatically ensure all seeded staff users have a StaffProfile
    staff_users = CustomUser.objects.filter(roles__code__in=['R01', 'R02', 'R03', 'R04', 'R05', 'R06'])
    for u in staff_users:
        if not hasattr(u, 'staff_profile'):
            role_code = u.roles.first().code if u.roles.exists() else 'STAFF'
            count = StaffProfile.objects.count() + 1
            staff_id = f"LIS/{role_code}/{timezone.now().year}/{count:04d}"
            StaffProfile.objects.create(
                user=u,
                staff_id=staff_id,
                department="Academics" if role_code == 'R06' else "Administration",
                education_level="Bachelor" if role_code == 'R06' else "Management",
                age=35,
                employment_status="PERMANENT"
            )

    staff_profiles = StaffProfile.objects.all().select_related('user', 'user__salary_config').order_by('user__first_name')
    roles = Role.objects.exclude(code__in=['R07', 'R08']).order_by('name') # Exclude Student and Parent

    return render(request, 'erp_core/administration/staff_enrollment.html', {
        'staff_profiles': staff_profiles,
        'roles': roles
    })

@login_required
def user_edit(request, user_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can manage users.")
        return redirect('dashboard')

    target_user = CustomUser.objects.get(id=user_id)
    roles = Role.objects.all()
    classes = Class.objects.all()

    student_profile = getattr(target_user, 'student_profile', None)
    staff_profile = getattr(target_user, 'staff_profile', None)

    if request.method == 'POST':
        target_user.email = request.POST.get('email')
        target_user.first_name = request.POST.get('first_name')
        target_user.last_name = request.POST.get('last_name')
        
        status = request.POST.get('status')
        if status in ['ACTIVE', 'REVOKED']:
            target_user.status = status

        target_user.save()

        # Update roles
        role_ids = request.POST.getlist('roles')
        target_user.roles.clear()
        for r_id in role_ids:
            role = Role.objects.get(id=r_id)
            target_user.roles.add(role)

        user_roles = [r.code for r in target_user.roles.all()]

        # Update or create profiles
        if 'R07' in user_roles:
            class_id = request.POST.get('class_id')
            student_id = request.POST.get('student_id')
            if class_id and student_id:
                class_obj = Class.objects.get(id=class_id)
                StudentProfile.objects.update_or_create(
                    user=target_user,
                    defaults={'student_id': student_id, 'current_class': class_obj}
                )
        elif any(c in ['R01', 'R02', 'R03', 'R04', 'R05', 'R06'] for c in user_roles):
            staff_id = request.POST.get('staff_id')
            department = request.POST.get('department')
            if staff_id:
                StaffProfile.objects.update_or_create(
                    user=target_user,
                    defaults={'staff_id': staff_id, 'department': department}
                )

        messages.success(request, f"User {target_user.username} successfully updated.")
        return redirect('user_list')

    return render(request, 'erp_core/administration/user_form.html', {
        'target_user': target_user,
        'roles': roles,
        'classes': classes,
        'student_profile': student_profile,
        'staff_profile': staff_profile,
        'is_create': False
    })

@login_required
def user_toggle_status(request, user_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can manage users.")
        return redirect('dashboard')

    target_user = CustomUser.objects.get(id=user_id)
    if target_user.status == 'ACTIVE':
        target_user.status = 'REVOKED'
        messages.warning(request, f"User {target_user.username} has been suspended.")
    else:
        target_user.status = 'ACTIVE'
        messages.success(request, f"User {target_user.username} is now active.")
    target_user.save()
    return redirect('user_list')

@login_required
def admin_change_password(request, user_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only the Director or Principal can manage passwords.")
        return redirect('dashboard')

    target_user = CustomUser.objects.get(id=user_id)
    if request.method == 'POST':
        new_pass = request.POST.get('new_password')
        confirm_pass = request.POST.get('confirm_password')

        if new_pass == confirm_pass:
            target_user.set_password(new_pass)
            target_user.is_temporary_password = True
            target_user.save()
            messages.success(request, f"Password successfully reset for {target_user.username}. Forced temporary password flow enabled.")
            return redirect('user_list')
        else:
            messages.error(request, "Passwords do not match.")

    return render(request, 'erp_core/administration/admin_change_password.html', {'target_user': target_user})

@login_required
def change_my_password(request):
    if request.method == 'POST':
        current_pass = request.POST.get('current_password')
        new_pass = request.POST.get('new_password')
        confirm_pass = request.POST.get('confirm_password')

        if not request.user.check_password(current_pass):
            messages.error(request, "Your current password is incorrect.")
            return render(request, 'erp_core/administration/change_my_password.html')

        if new_pass != confirm_pass:
            messages.error(request, "New passwords do not match.")
            return render(request, 'erp_core/administration/change_my_password.html')

        try:
            validate_password(new_pass, user=request.user)
            if not any(c.isupper() for c in new_pass):
                raise ValidationError("Password must contain at least one uppercase letter.")
            if not any(c.isdigit() for c in new_pass):
                raise ValidationError("Password must contain at least one number.")
            if not any(not c.isalnum() for c in new_pass):
                raise ValidationError("Password must contain at least one special character.")

            request.user.set_password(new_pass)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Your password has been successfully changed!")
            return redirect('dashboard')
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)

    return render(request, 'erp_core/administration/change_my_password.html')

# 2. Subject & Area Configuration views
@login_required
def subject_setup(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if not any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes):
        messages.error(request, "You do not have permission to manage subjects.")
        return redirect('dashboard')

    subjects = Subject.objects.all().order_by('level', 'name')

    if request.method == 'POST':
        name = request.POST.get('name')
        level = request.POST.get('level')

        if name and level:
            Subject.objects.create(name=name, level=level)
            messages.success(request, f"Subject/Area '{name}' added successfully.")
            return redirect('subject_setup')

    return render(request, 'erp_core/administration/subject_setup.html', {'subjects': subjects})

@login_required
def subject_delete(request, subject_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if not any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes):
        messages.error(request, "You do not have permission to delete subjects.")
        return redirect('dashboard')

    subject = Subject.objects.get(id=subject_id)
    subject.delete()
    messages.success(request, "Subject deleted successfully.")
    return redirect('subject_setup')

# 3. Teacher Subject Assignment views
@login_required
def teacher_assignment_setup(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if not any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes):
        messages.error(request, "You do not have permission to manage teacher assignments.")
        return redirect('dashboard')

    assignments = TeacherSubjectAssignment.objects.all().order_by('class_obj', 'subject')
    teachers = CustomUser.objects.filter(roles__code='R06')
    classes = Class.objects.all()
    subjects = Subject.objects.all()

    if request.method == 'POST':
        teacher_id = request.POST.get('teacher_id')
        class_id = request.POST.get('class_id')
        subject_id = request.POST.get('subject_id')

        if teacher_id and class_id and subject_id:
            teacher = CustomUser.objects.get(id=teacher_id)
            class_obj = Class.objects.get(id=class_id)
            subject = Subject.objects.get(id=subject_id)

            TeacherSubjectAssignment.objects.get_or_create(
                teacher=teacher,
                class_obj=class_obj,
                subject=subject
            )
            messages.success(request, f"Assigned {teacher.get_full_name()} to {class_obj.name} - {subject.name}")
            return redirect('teacher_assignment_setup')

    return render(request, 'erp_core/administration/teacher_assignment.html', {
        'assignments': assignments,
        'teachers': teachers,
        'classes': classes,
        'subjects': subjects,
    })

@login_required
def teacher_assignment_delete(request, assignment_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if not any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes):
        messages.error(request, "You do not have permission to manage assignments.")
        return redirect('dashboard')

    assignment = TeacherSubjectAssignment.objects.get(id=assignment_id)
    assignment.delete()
    messages.success(request, "Assignment deleted successfully.")
    return redirect('teacher_assignment_setup')

# 4. Student Attendance views
@login_required
def attendance_registry(request):
    user = request.user
    role_codes = [role.code for role in user.roles.all()]
    is_admin = any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes)

    classes = Class.objects.all()
    selected_class_id = request.GET.get('class_id')
    date_str = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
    selected_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()

    selected_class = None
    students_data = []

    if selected_class_id:
        selected_class = Class.objects.get(id=selected_class_id)
        
        # Enforce Class Teacher constraint
        if 'R06' in role_codes and not is_admin:
            if selected_class.class_teacher != user:
                messages.error(request, f"You are not assigned as the class teacher for {selected_class.name}. Only class teachers can view attendance.")
                return redirect('attendance_registry')

        students = StudentProfile.objects.filter(current_class=selected_class).order_by('user__first_name')
        
        for s in students:
            att = StudentAttendance.objects.filter(student=s, date=selected_date).first()
            exc = AttendanceException.objects.filter(user=s.user, date=selected_date).first()
            
            status = 'ABSENT'
            check_in = None
            check_out = None
            source = 'Biometric'
            reason = ''
            
            if exc:
                status = exc.exception_type
                source = 'Manual Exception'
                reason = exc.reason
            elif att:
                status = att.status
                check_in = att.check_in_time
                check_out = att.check_out_time
            
            students_data.append({
                'student': s,
                'status': status,
                'check_in': check_in,
                'check_out': check_out,
                'source': source,
                'reason': reason
            })

    return render(request, 'erp_core/administration/attendance.html', {
        'classes': classes,
        'selected_class': selected_class,
        'selected_date': selected_date,
        'students_data': students_data,
        'is_admin': is_admin
    })

@login_required
def save_attendance(request):
    if request.method == 'POST':
        class_id = request.POST.get('class_id')
        date_str = request.POST.get('date')
        selected_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()

        user = request.user
        role_codes = [role.code for role in user.roles.all()]
        is_admin = any(c in ['R01', 'R02', 'R04', 'R05'] for c in role_codes)

        if class_id:
            class_obj = Class.objects.get(id=class_id)

            # Enforce Class Teacher constraint
            if 'R06' in role_codes and not is_admin:
                if class_obj.class_teacher != user:
                    messages.error(request, "Permission denied.")
                    return redirect('attendance_registry')

            students = StudentProfile.objects.filter(current_class=class_obj)
            for s in students:
                status = request.POST.get(f'status_{s.id}')
                remarks = request.POST.get(f'remarks_{s.id}', '')
                if status:
                    StudentAttendance.objects.update_or_create(
                        student=s,
                        date=selected_date,
                        defaults={
                            'status': status,
                            'remarks': remarks,
                            'recorded_by': request.user
                        }
                    )
            messages.success(request, f"Attendance for {class_obj.name} on {date_str} successfully saved.")
            return redirect(f"{reverse('attendance_registry')}?class_id={class_id}&date={date_str}")

    return redirect('attendance_registry')

# 5. Report Cards Builder
@login_required
def report_card_generator(request):
    classes = Class.objects.all()
    selected_class_id = request.GET.get('class_id')
    selected_class = None
    students = []

    if selected_class_id:
        selected_class = Class.objects.get(id=selected_class_id)
        students = StudentProfile.objects.filter(current_class=selected_class)

    return render(request, 'erp_core/administration/report_card_generator.html', {
        'classes': classes,
        'selected_class': selected_class,
        'students': students
    })

@login_required
def view_report_card(request, student_id, term, year):
    student = StudentProfile.objects.get(id=student_id)
    class_obj = student.current_class
    framework = request.GET.get('framework', 'A-G')

    if class_obj.level_type == 'EARLY_YEARS':
        progress = LearningAreaProgress.objects.filter(
            student=student,
            term=term,
            academic_year=year
        )
        return render(request, 'erp_core/administration/report_card_early_years.html', {
            'student': student,
            'term': term,
            'year': year,
            'progress': progress
        })
    else:
        raw_marks = RawMark.objects.filter(
            student=student,
            term=term,
            academic_year=year
        )
        boundaries = GradeBoundary.objects.filter(framework=framework).order_by('-min_percentage')
        
        grades_list = []
        total_pct = 0
        count = 0
        for rm in raw_marks:
            pct = rm.get_percentage()
            total_pct += pct
            count += 1
            matched_grade = 'N/A'
            for b in boundaries:
                if pct >= b.min_percentage:
                    matched_grade = b.grade_letter
                    break
            grades_list.append({
                'mark': rm,
                'percentage': pct,
                'grade': matched_grade
            })
            
        average_pct = int(total_pct / count) if count > 0 else 0
        overall_grade = 'N/A'
        for b in boundaries:
            if average_pct >= b.min_percentage:
                overall_grade = b.grade_letter
                break

        return render(request, 'erp_core/administration/report_card_primary.html', {
            'student': student,
            'term': term,
            'year': year,
            'grades_list': grades_list,
            'average_pct': average_pct,
            'overall_grade': overall_grade,
            'framework': framework
        })

# 6. Financial Statements
@login_required
def financial_statements(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if not any(c in ['R01', 'R02', 'R03'] for c in role_codes):
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    payments = FeePayment.objects.all().order_by('-created_at')[:50]
    total_fees_collected = FeePayment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0

    total_due = FeeStructure.objects.all().aggregate(Sum('amount'))['amount__sum'] or 0
    total_collected = FeePayment.objects.all().aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    outstanding_dues = max(0, total_due - total_collected)

    expenses = Expense.objects.all().order_by('-date')[:50]
    total_expenses = Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0

    payroll_runs = Payroll.objects.all().order_by('-year', '-month')
    total_payroll = Payslip.objects.filter(status='PAID').aggregate(Sum('net_salary'))['net_salary__sum'] or 0

    return render(request, 'erp_core/administration/financial_statement.html', {
        'payments': payments,
        'total_fees_collected': total_fees_collected,
        'outstanding_dues': outstanding_dues,
        'expenses': expenses,
        'total_expenses': total_expenses,
        'payroll_runs': payroll_runs,
        'total_payroll': total_payroll,
    })

# 7. Inventory Management Views
@login_required
def inventory_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    items = StockItem.objects.all().order_by('name')
    movements = StockMovement.objects.all().order_by('-date', '-created_at')
    
    total_items = items.count()
    low_stock_count = sum(1 for item in items if item.quantity <= item.reorder_level and item.quantity > 0)
    out_of_stock_count = sum(1 for item in items if item.quantity == 0)
    total_value = sum(item.quantity * item.unit_price for item in items)

    return render(request, 'erp_core/inventory/inventory_list.html', {
        'items': items,
        'movements': movements,
        'total_items': total_items,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'total_value': total_value,
    })

@login_required
def inventory_create(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    from decimal import Decimal
    if request.method == 'POST':
        name = request.POST.get('name')
        category = request.POST.get('category')
        quantity = Decimal(request.POST.get('quantity', '0'))
        unit = request.POST.get('unit', 'pcs')
        unit_price = Decimal(request.POST.get('unit_price', '0'))
        reorder_level = Decimal(request.POST.get('reorder_level', '10'))

        StockItem.objects.create(
            name=name,
            category=category,
            quantity=quantity,
            unit=unit,
            unit_price=unit_price,
            reorder_level=reorder_level
        )
        messages.success(request, f"Inventory item '{name}' added successfully.")
        return redirect('inventory_list')

    categories = StockItem.CATEGORY_CHOICES
    return render(request, 'erp_core/inventory/inventory_form.html', {
        'categories': categories,
        'is_create': True
    })

@login_required
def inventory_update(request, item_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    item = StockItem.objects.get(id=item_id)
    from decimal import Decimal

    if request.method == 'POST':
        item.name = request.POST.get('name')
        item.category = request.POST.get('category')
        item.quantity = Decimal(request.POST.get('quantity', '0'))
        item.unit = request.POST.get('unit', 'pcs')
        item.unit_price = Decimal(request.POST.get('unit_price', '0'))
        item.reorder_level = Decimal(request.POST.get('reorder_level', '10'))
        item.save()

        messages.success(request, f"Inventory item '{item.name}' updated successfully.")
        return redirect('inventory_list')

    categories = StockItem.CATEGORY_CHOICES
    return render(request, 'erp_core/inventory/inventory_form.html', {
        'item': item,
        'categories': categories,
        'is_create': False
    })

@login_required
def stock_movement_create(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    from decimal import Decimal
    if request.method == 'POST':
        stock_item_id = request.POST.get('stock_item_id')
        movement_type = request.POST.get('movement_type')
        quantity = Decimal(request.POST.get('quantity', '0'))
        issued_to_id = request.POST.get('issued_to')
        date = request.POST.get('date', timezone.now().date())
        remarks = request.POST.get('remarks')

        try:
            stock_item = StockItem.objects.get(id=stock_item_id)
            issued_to = None
            if issued_to_id:
                issued_to = CustomUser.objects.get(id=issued_to_id)

            if movement_type == 'OUT' and stock_item.quantity < quantity:
                messages.error(request, f"Insufficient stock for {stock_item.name}. Available: {stock_item.quantity} {stock_item.unit}.")
            else:
                StockMovement.objects.create(
                    stock_item=stock_item,
                    movement_type=movement_type,
                    quantity=quantity,
                    date=date,
                    issued_to=issued_to,
                    remarks=remarks
                )
                if movement_type == 'IN':
                    stock_item.quantity += quantity
                else:
                    stock_item.quantity -= quantity
                stock_item.save()
                messages.success(request, f"Stock movement recorded successfully.")
                return redirect('inventory_list')
        except Exception as e:
            messages.error(request, f"Error saving stock movement: {str(e)}")

    stock_items = StockItem.objects.all().order_by('name')
    recipients = CustomUser.objects.exclude(roles__code__in=['R07', 'R08']).distinct().order_by('first_name')
    
    return render(request, 'erp_core/inventory/stock_movement_form.html', {
        'stock_items': stock_items,
        'recipients': recipients,
    })



# 8. Transport Management Views
@login_required
def transport_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    routes = TransportRoute.objects.all().order_by('name')
    students_no_route = StudentProfile.objects.filter(transport_route__isnull=True)
    
    total_routes = routes.count()
    total_assigned = StudentProfile.objects.filter(transport_route__isnull=False).count()
    termly_revenue = sum(route.route_fee * route.assigned_students.count() for route in routes)

    return render(request, 'erp_core/transport/transport_list.html', {
        'routes': routes,
        'students_no_route': students_no_route,
        'total_routes': total_routes,
        'total_assigned': total_assigned,
        'termly_revenue': termly_revenue,
    })

@login_required
def transport_create(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        name = request.POST.get('name')
        vehicle_number = request.POST.get('vehicle_number')
        driver_name = request.POST.get('driver_name')
        driver_phone = request.POST.get('driver_phone')
        route_fee = float(request.POST.get('route_fee', 0))
        capacity = int(request.POST.get('capacity', 30))

        TransportRoute.objects.create(
            name=name,
            vehicle_number=vehicle_number,
            driver_name=driver_name,
            driver_phone=driver_phone,
            route_fee=route_fee,
            capacity=capacity
        )
        messages.success(request, f"Transport route '{name}' created successfully.")
        return redirect('transport_list')

    return render(request, 'erp_core/transport/transport_form.html', {
        'is_create': True
    })

@login_required
def transport_assign_student(request, student_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    student = StudentProfile.objects.get(id=student_id)
    if request.method == 'POST':
        route_id = request.POST.get('route_id')
        if route_id:
            route = TransportRoute.objects.get(id=route_id)
            if route.assigned_students.count() >= route.capacity:
                messages.error(request, f"Route '{route.name}' is already at full capacity.")
            else:
                student.transport_route = route
                student.save()
                messages.success(request, f"Assigned {student.user.get_full_name()} to {route.name}.")
        else:
            student.transport_route = None
            student.save()
            messages.info(request, f"Removed transport assignment for {student.user.get_full_name()}.")
        return redirect('transport_list')

    routes = TransportRoute.objects.all()
    return render(request, 'erp_core/transport/assign_student.html', {
        'student': student,
        'routes': routes
    })

@login_required
def procurement_requisitions(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    # Get items where quantity is below or equal to reorder_level
    from django.db.models import F
    low_stock_items = StockItem.objects.filter(quantity__lte=F('reorder_level')).order_by('name')
    
    requisition_list = []
    for item in low_stock_items:
        deficit = max(0, item.reorder_level - item.quantity)
        requisition_list.append({
            'item': item,
            'stock': item.quantity,
            'reorder_level': item.reorder_level,
            'deficit': deficit,
        })

    return render(request, 'erp_core/inventory/procurement_requisitions.html', {
        'requisition_list': requisition_list
    })


# 9. Biometric Integration Views
@csrf_exempt
@require_POST
def api_biometric_log_push(request):
    # Verify API key
    api_key = request.headers.get('X-API-Key')
    if api_key != "leaders-erp-secure-token-2026":
        return JsonResponse({"status": "error", "message": "Unauthorized API key"}, status=401)

    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    serial_number = data.get('serial_number')
    biometric_id = data.get('biometric_id')
    timestamp_str = data.get('timestamp')
    direction = data.get('direction', 'AUTO')
    verify_mode = data.get('verify_mode', 'FINGERPRINT')

    if not biometric_id or not timestamp_str or not serial_number:
        return JsonResponse({"status": "error", "message": "Missing required fields"}, status=400)

    try:
        timestamp = timezone.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid timestamp format"}, status=400)

    # 1. Fetch or create device
    device, _ = BiometricDevice.objects.get_or_create(
        serial_number=serial_number,
        defaults={
            'name': f"Terminal {serial_number[-6:]}",
            'location': "Automatic Sync Gateway",
            'status': 'ONLINE'
        }
    )
    device.status = 'ONLINE'
    device.save()

    # 2. Resolve User
    user = CustomUser.objects.filter(biometric_id=biometric_id).first()

    # 3. Create raw log entry
    log = BiometricLog.objects.create(
        device=device,
        biometric_id=biometric_id,
        user=user,
        timestamp=timestamp,
        direction=direction,
        verification_type=verify_mode,
        processed=True
    )

    if not user:
        return JsonResponse({
            "status": "success",
            "message": f"Log recorded for unregistered biometric ID {biometric_id}"
        })

    # 4. Update Daily Attendance
    punch_date = timestamp.date()
    punch_time = timestamp.time()
    role_codes = [r.code for r in user.roles.all()]

    # Skip if manual exception exists
    has_exception = AttendanceException.objects.filter(user=user, date=punch_date).exists()
    if has_exception:
        return JsonResponse({"status": "success", "message": "Attendance skipped due to manual exception"})

    if 'R07' in role_codes:
        # Student
        student_profile = getattr(user, 'student_profile', None)
        if student_profile:
            att, created = StudentAttendance.objects.get_or_create(
                student=student_profile,
                date=punch_date,
                defaults={
                    'status': 'LATE' if punch_time > timezone.datetime.strptime('08:00:00', '%H:%M:%S').time() else 'PRESENT',
                    'check_in_time': punch_time,
                    'recorded_by': user
                }
            )
            if not created:
                att.check_out_time = punch_time
                att.save()

    elif any(code in ['R01', 'R02', 'R03', 'R04', 'R05', 'R06'] for code in role_codes):
        # Staff
        att, created = StaffAttendance.objects.get_or_create(
            staff=user,
            date=punch_date,
            defaults={
                'status': 'LATE' if punch_time > timezone.datetime.strptime('08:30:00', '%H:%M:%S').time() else 'PRESENT',
                'check_in_time': punch_time,
                'recorded_by': user
            }
        )
        if not created:
            att.check_out_time = punch_time
            # Calculate worked hours
            if att.check_in_time and att.check_out_time:
                delta = timezone.datetime.combine(punch_date, att.check_out_time) - timezone.datetime.combine(punch_date, att.check_in_time)
                att.worked_hours = round(delta.total_seconds() / 3600.0, 2)
            att.save()

    return JsonResponse({"status": "success", "message": "Log processed successfully"})

@login_required
def biometric_registration(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only Administrators can register biometric mappings.")
        return redirect('dashboard')

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        biometric_id = request.POST.get('biometric_id', '').strip()
        
        if user_id:
            try:
                target_user = CustomUser.objects.get(id=user_id)
                if biometric_id:
                    # Check duplicate
                    duplicate = CustomUser.objects.filter(biometric_id=biometric_id).exclude(id=user_id).first()
                    if duplicate:
                        messages.error(request, f"Biometric ID '{biometric_id}' is already assigned to {duplicate.get_full_name()}.")
                    else:
                        target_user.biometric_id = biometric_id
                        target_user.save()
                        messages.success(request, f"Fingerprint ID {biometric_id} registered to {target_user.get_full_name()}.")
                else:
                    target_user.biometric_id = None
                    target_user.save()
                    messages.info(request, f"Biometric assignment removed for {target_user.get_full_name()}.")
            except CustomUser.DoesNotExist:
                pass
            return redirect('biometric_registration')

    # Find users with no biometric_id
    students = StudentProfile.objects.all().order_by('user__first_name')
    staff = StaffProfile.objects.all().order_by('user__first_name')
    
    return render(request, 'erp_core/administration/biometric_registration.html', {
        'students': students,
        'staff': staff
    })

@login_required
def biometric_dashboard(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes and 'R03' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    devices = BiometricDevice.objects.all().order_by('name')
    recent_logs = BiometricLog.objects.all().order_by('-timestamp')[:50]
    
    # Calculate Stats
    today = timezone.now().date()
    total_scans_today = BiometricLog.objects.filter(timestamp__date=today).count()
    unregistered_scans = BiometricLog.objects.filter(user__isnull=True).count()
    active_devices = devices.filter(status='ONLINE').count()
    
    students_present = StudentAttendance.objects.filter(date=today, status__in=['PRESENT', 'LATE']).count()
    staff_present = StaffAttendance.objects.filter(date=today, status__in=['PRESENT', 'LATE']).count()

    return render(request, 'erp_core/administration/biometric_dashboard.html', {
        'devices': devices,
        'recent_logs': recent_logs,
        'total_scans_today': total_scans_today,
        'unregistered_scans': unregistered_scans,
        'active_devices': active_devices,
        'students_present': students_present,
        'staff_present': staff_present,
    })

@login_required
def attendance_exceptions(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        date_str = request.POST.get('date')
        exception_type = request.POST.get('exception_type', 'PRESENT')
        reason = request.POST.get('reason')

        if user_id and date_str:
            try:
                target_user = CustomUser.objects.get(id=user_id)
                exc_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
                
                # Save Exception
                AttendanceException.objects.update_or_create(
                    user=target_user,
                    date=exc_date,
                    defaults={
                        'exception_type': exception_type,
                        'reason': reason,
                        'approved_by': request.user
                    }
                )

                # Dynamically write into summary tables
                target_roles = [r.code for r in target_user.roles.all()]
                if 'R07' in target_roles:
                    profile = target_user.student_profile
                    StudentAttendance.objects.update_or_create(
                        student=profile,
                        date=exc_date,
                        defaults={
                            'status': exception_type,
                            'remarks': f"Manual Exception: {reason}",
                            'recorded_by': request.user
                        }
                    )
                else:
                    StaffAttendance.objects.update_or_create(
                        staff=target_user,
                        date=exc_date,
                        defaults={
                            'status': exception_type,
                            'remarks': f"Manual Exception: {reason}",
                            'recorded_by': request.user
                        }
                    )
                messages.success(request, f"Manual exception logged successfully for {target_user.get_full_name()}.")
            except Exception as e:
                messages.error(request, f"Error logging exception: {str(e)}")
            return redirect('attendance_exceptions')

    users = CustomUser.objects.all().order_by('first_name')
    exceptions = AttendanceException.objects.all().order_by('-date')[:50]
    
    return render(request, 'erp_core/administration/attendance_exceptions.html', {
        'users': users,
        'exceptions': exceptions
    })

@login_required
def kitchen_led_display(request):
    today = timezone.now().date()
    students_present = StudentAttendance.objects.filter(date=today, status__in=['PRESENT', 'LATE']).count()
    staff_present = StaffAttendance.objects.filter(date=today, status__in=['PRESENT', 'LATE']).count()
    
    return render(request, 'erp_core/kitchen/led_display.html', {
        'students_present': students_present,
        'staff_present': staff_present,
        'today': today,
    })

@login_required
def kitchen_led_data_api(request):
    today = timezone.now().date()
    students_present = StudentAttendance.objects.filter(date=today, status__in=['PRESENT', 'LATE']).count()
    staff_present = StaffAttendance.objects.filter(date=today, status__in=['PRESENT', 'LATE']).count()
    
    return JsonResponse({
        'students_present': students_present,
        'staff_present': staff_present,
        'total_present': students_present + staff_present,
        'date': today.isoformat()
    })

@csrf_exempt
@require_POST
def bank_deposit_webhook(request):
    import json
    import hashlib
    from decimal import Decimal
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    # Expected payload: {ref, amount, account_number, date, sender_name}
    student_ref = data.get("ref")
    amount_str = data.get("amount")
    account_number = data.get("account_number", "")
    deposit_date_str = data.get("date")
    sender_name = data.get("sender_name", "")

    if not student_ref or not amount_str:
        return JsonResponse({"status": "error", "message": "Missing required fields (ref, amount)"}, status=400)

    try:
        amount = Decimal(str(amount_str))
    except ValueError:
        return JsonResponse({"status": "error", "message": "Invalid amount value"}, status=400)

    # Determine unique reference number (use transaction_id if sent, else hash key details)
    payload_str = f"{student_ref}-{amount_str}-{account_number}-{deposit_date_str}-{sender_name}"
    ref_number = data.get("transaction_id") or data.get("ref_number") or hashlib.md5(payload_str.encode('utf-8')).hexdigest().upper()[:12]

    # Map account_number dynamically based on database config
    config = IntegrationConfig.get_solo()
    bank_name = 'CRDB' # Default
    account_number_str = str(account_number).strip()
    if account_number_str == config.crdb_account:
        bank_name = 'CRDB'
    elif account_number_str == config.exim_account:
        bank_name = 'EXIM'
    elif account_number_str == config.pbz_account:
        bank_name = 'PBZ'
    else:
        # Fallback to substring mapping if exact account is not matched
        account_number_clean = account_number_str.lower()
        if 'exim' in account_number_clean or account_number_clean.startswith('112'):
            bank_name = 'EXIM'
        elif 'pbz' in account_number_clean or account_number_clean.startswith('212'):
            bank_name = 'PBZ'
        elif 'crdb' in account_number_clean or account_number_clean.startswith('015') or account_number_clean.startswith('01'):
            bank_name = 'CRDB'

    # Parse date if sent
    deposit_date = timezone.now()
    if deposit_date_str:
        try:
            deposit_date = timezone.datetime.fromisoformat(deposit_date_str.replace('Z', '+00:00'))
        except ValueError:
            pass

    # 1. Match Student (exact or substring check)
    student = StudentProfile.objects.filter(student_id__iexact=student_ref.strip()).first()
    parent = None
    
    if not student:
        # Try finding if student ID is a substring of the reference
        for s in StudentProfile.objects.all():
            if s.student_id.lower() in student_ref.lower():
                student = s
                break
                
    if student:
        parent = student.parents.first()

    # 2. Create BankDeposit record
    try:
        deposit = BankDeposit.objects.create(
            ref_number=ref_number,
            student_ref=student_ref,
            bank_name=bank_name,
            account_number=account_number,
            sender_name=sender_name,
            amount=amount,
            deposit_date=deposit_date,
            student=student,
            parent=parent
        )
        return JsonResponse({
            "status": "success",
            "message": f"Bank deposit {ref_number} logged successfully",
            "matched_student": student.user.get_full_name() if student else "None",
            "matched_parent": parent.user.get_full_name() if parent else "None"
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Database error: {str(e)}"}, status=500)

@login_required
def bank_deposits_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    deposits = BankDeposit.objects.all().order_by('-created_at')
    return render(request, 'erp_core/financials/bank_deposits_list.html', {
        'deposits': deposits
    })

@login_required
def allocate_bank_deposit(request, deposit_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes:
        messages.error(request, "Only Accountant can allocate bank deposits.")
        return redirect('bank_deposits_list')

    deposit = BankDeposit.objects.get(id=deposit_id)
    if deposit.is_fully_allocated:
        messages.warning(request, "This deposit is already fully allocated.")
        return redirect('bank_deposits_list')

    from decimal import Decimal
    
    # Find the siblings (students sharing the same parent)
    siblings = []
    if deposit.parent:
        siblings = deposit.parent.students.all()
    elif deposit.student:
        siblings = [deposit.student]

    # Calculate outstanding dues for each sibling
    siblings_data = []
    for sibling in siblings:
        fee_structures = FeeStructure.objects.filter(class_obj=sibling.current_class)
        dues = []
        for fs in fee_structures:
            paid = FeePayment.objects.filter(student=sibling, fee_structure=fs).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
            balance = fs.amount - paid
            if balance > 0:
                dues.append({
                    'fee_structure': fs,
                    'balance': balance
                })
        if dues:
            siblings_data.append({
                'student': sibling,
                'dues': dues
            })

    if request.method == 'POST':
        import random
        rand_part = random.randint(1000, 9999)
        receipt_no = f"BANK-{timezone.now().strftime('%Y%m%d')}-{rand_part}"

        allocated_payments = []
        total_allocated_this_time = Decimal('0.00')
        idx = 1

        for key, val in request.POST.items():
            if key.startswith('allocation_') and val:
                try:
                    allocated_val = Decimal(val)
                    if allocated_val <= 0:
                        continue
                        
                    parts = key.split('_')
                    student_id = int(parts[1])
                    fs_id = int(parts[2])
                    
                    student = StudentProfile.objects.get(id=student_id)
                    fs = FeeStructure.objects.get(id=fs_id)
                    
                    unique_receipt_no = f"{receipt_no}-{idx}"
                    payment = FeePayment.objects.create(
                        student=student,
                        fee_structure=fs,
                        amount_paid=allocated_val,
                        payment_method='BANK',
                        reference_number=deposit.ref_number,
                        receipt_number=unique_receipt_no,
                        notes=f"Allocated from bank deposit {deposit.ref_number} ({deposit.bank_name})",
                        recorded_by=request.user
                    )
                    AccountingService.record_fee_payment(payment, request.user)
                    allocated_payments.append(payment)
                    total_allocated_this_time += allocated_val
                    idx += 1
                except Exception as e:
                    messages.error(request, f"Error processing allocation: {str(e)}")

        if total_allocated_this_time > 0:
            deposit.allocated_amount += total_allocated_this_time
            if deposit.allocated_amount >= deposit.amount:
                deposit.is_fully_allocated = True
            deposit.save()

            messages.success(request, f"Successfully allocated TZS {total_allocated_this_time:,.2f}. Receipt {receipt_no} generated.")

            # Trigger WhatsApp PDF Receipt sending
            from .whatsapp_service import generate_receipt_pdf, send_whatsapp_receipt_pdf
            
            parent_phone = None
            if deposit.parent and deposit.parent.user.phone_number:
                parent_phone = deposit.parent.user.phone_number
            elif deposit.student and deposit.student.parents.exists():
                parent_phone = deposit.student.parents.first().user.phone_number
            elif deposit.student and deposit.student.user.phone_number:
                parent_phone = deposit.student.user.phone_number

            if parent_phone:
                pdf_path = generate_receipt_pdf(allocated_payments, receipt_no)
                if pdf_path:
                    send_whatsapp_receipt_pdf(parent_phone, pdf_path, receipt_no)

            return redirect('bank_deposits_list')
        else:
            messages.warning(request, "No allocations were made.")

    return render(request, 'erp_core/financials/allocate_bank_deposit.html', {
        'deposit': deposit,
        'siblings_data': siblings_data,
        'unallocated_amount': deposit.unallocated_amount(),
    })

@login_required
def integration_settings(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R01' not in role_codes:
        messages.error(request, "Access denied. Only Directors can access integration settings.")
        return redirect('dashboard')

    config = IntegrationConfig.get_solo()

    if request.method == 'POST':
        config.crdb_account = request.POST.get('crdb_account')
        config.exim_account = request.POST.get('exim_account')
        config.pbz_account = request.POST.get('pbz_account')
        
        config.whatsapp_provider = request.POST.get('whatsapp_provider')
        config.whatsapp_api_url = request.POST.get('whatsapp_api_url')
        config.whatsapp_api_key = request.POST.get('whatsapp_api_key')
        config.whatsapp_sender_number = request.POST.get('whatsapp_sender_number')
        config.save()
        
        messages.success(request, "Integration configurations updated successfully.")
        return redirect('integration_settings')

    providers = IntegrationConfig.PROVIDER_CHOICES
    return render(request, 'erp_core/administration/integration_settings.html', {
        'config': config,
        'providers': providers,
    })


# ==============================================================================
#                      COMPREHENSIVE ACCOUNTING MODULE VIEWS
# ==============================================================================

@login_required
def chart_of_accounts(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    accounts = ChartOfAccounts.objects.all().order_by('code')
    types = AccountType.choices
    sub_types = AccountSubType.choices

    if request.method == 'POST':
        code = request.POST.get('code')
        name = request.POST.get('name')
        account_type = request.POST.get('account_type')
        account_sub_type = request.POST.get('account_sub_type')
        normal_balance = request.POST.get('normal_balance')
        description = request.POST.get('description', '')

        if code and name and account_type and normal_balance:
            try:
                ChartOfAccounts.objects.create(
                    code=code,
                    name=name,
                    account_type=account_type,
                    account_sub_type=account_sub_type,
                    normal_balance=normal_balance,
                    description=description
                )
                messages.success(request, f"Account {code} - {name} created successfully.")
                return redirect('chart_of_accounts')
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")

    return render(request, 'erp_core/financials/chart_of_accounts.html', {
        'accounts': accounts,
        'types': types,
        'sub_types': sub_types,
    })

@login_required
def journal_entries_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    entries = JournalEntry.objects.all().prefetch_related('lines').order_by('-posting_date', '-created_at')
    accounts = ChartOfAccounts.objects.filter(is_active=True)

    if request.method == 'POST':
        description = request.POST.get('description')
        posting_date = request.POST.get('posting_date')
        entry_type = request.POST.get('entry_type', 'MANUAL')

        # Extract lines
        line_indices = [k.replace('line_account_', '') for k in request.POST.keys() if k.startswith('line_account_')]
        
        try:
            with transaction.atomic():
                period = AccountingService.get_or_create_period(timezone.datetime.strptime(posting_date, '%Y-%m-%d').date())
                journal = JournalEntry.objects.create(
                    entry_type=entry_type,
                    description=description,
                    posting_date=posting_date,
                    period=period,
                    created_by=request.user,
                    status='DRAFT'
                )

                total_debits = Decimal('0')
                total_credits = Decimal('0')

                for idx in line_indices:
                    acc_id = request.POST.get(f'line_account_{idx}')
                    desc = request.POST.get(f'line_desc_{idx}', '')
                    debit = Decimal(request.POST.get(f'line_debit_{idx}') or '0')
                    credit = Decimal(request.POST.get(f'line_credit_{idx}') or '0')

                    if not acc_id:
                        continue
                    if debit == 0 and credit == 0:
                        continue

                    account = ChartOfAccounts.objects.get(id=acc_id)
                    JournalEntryLine.objects.create(
                        journal=journal,
                        account=account,
                        description=desc or description,
                        debit_amount=debit,
                        credit_amount=credit
                    )
                    total_debits += debit
                    total_credits += credit

                if abs(total_debits - total_credits) >= Decimal('0.01'):
                    raise ValueError(f"Journal entry is not balanced. Debits: {total_debits}, Credits: {total_credits}")

                if 'post_directly' in request.POST:
                    journal.post(request.user)
                    messages.success(request, f"Journal entry {journal.reference} created and posted.")
                else:
                    messages.success(request, f"Journal entry {journal.reference} created as Draft.")
                
                return redirect('journal_entries_list')
        except Exception as e:
            messages.error(request, f"Failed to save Journal: {str(e)}")

    return render(request, 'erp_core/financials/journal_entries.html', {
        'entries': entries,
        'accounts': accounts,
    })

@login_required
def post_journal_entry(request, entry_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            entry = JournalEntry.objects.get(id=entry_id)
            entry.post(request.user)
            messages.success(request, f"Successfully posted Journal Entry {entry.reference}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
    return redirect('journal_entries_list')

@login_required
def reverse_journal_entry(request, entry_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        reason = request.POST.get('reason', 'Manual Reversal')
        try:
            entry = JournalEntry.objects.get(id=entry_id)
            reversal = entry.reverse(request.user, reason=reason)
            messages.success(request, f"Journal entry reversed. Reversal entry {reversal.reference} created and posted.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
    return redirect('journal_entries_list')

@login_required
def bills_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    bills = Bill.objects.all().order_by('-bill_date')
    expense_accounts = ChartOfAccounts.objects.filter(account_type='EXPENSE', is_active=True)
    bank_accounts = BankAccount.objects.filter(is_active=True)

    if request.method == 'POST':
        if 'create_bill' in request.POST:
            vendor_name = request.POST.get('vendor_name')
            bill_type = request.POST.get('bill_type')
            bill_date = request.POST.get('bill_date')
            due_date = request.POST.get('due_date')
            subtotal = Decimal(request.POST.get('subtotal') or '0')
            tax_rate = Decimal(request.POST.get('tax_rate') or '0')
            expense_acc_id = request.POST.get('expense_account_id')
            description = request.POST.get('description', '')

            try:
                expense_account = ChartOfAccounts.objects.get(id=expense_acc_id)
                bill = Bill.objects.create(
                    vendor_name=vendor_name,
                    bill_type=bill_type,
                    bill_date=bill_date,
                    due_date=due_date,
                    subtotal=subtotal,
                    tax_rate=tax_rate,
                    expense_account=expense_account,
                    description=description,
                    created_by=request.user,
                    status='DRAFT'
                )
                # Auto post double entry for the bill
                AccountingService.record_bill(bill, request.user)
                messages.success(request, f"Bill {bill.reference} created and approved.")
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")
            return redirect('bills_list')

    return render(request, 'erp_core/financials/bills.html', {
        'bills': bills,
        'expense_accounts': expense_accounts,
        'bank_accounts': bank_accounts,
    })

@login_required
def pay_bill(request, bill_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount') or '0')
        payment_method = request.POST.get('payment_method')
        bank_acc_id = request.POST.get('bank_account_id')
        notes = request.POST.get('notes', '')

        try:
            bill = Bill.objects.get(id=bill_id)
            bank_account = BankAccount.objects.get(id=bank_acc_id) if bank_acc_id else None
            
            bill_payment = BillPayment.objects.create(
                bill=bill,
                payment_date=timezone.now().date(),
                amount=amount,
                payment_method=payment_method,
                bank_account=bank_account,
                notes=notes,
                created_by=request.user
            )
            # Create payment journal entries
            AccountingService.record_bill_payment(bill_payment, request.user)
            messages.success(request, f"Recorded payment of TZS {amount:,.2f} for Bill {bill.reference}")
        except Exception as e:
            messages.error(request, f"Error paying bill: {str(e)}")

    return redirect('bills_list')

@login_required
def fixed_assets_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    assets = FixedAsset.objects.all().order_by('asset_code')
    asset_accounts = ChartOfAccounts.objects.filter(account_sub_type='FIXED_ASSET', is_active=True)
    dep_accounts = ChartOfAccounts.objects.filter(account_sub_type='DEPRECIATION', is_active=True)
    accum_accounts = ChartOfAccounts.objects.filter(account_type='ASSET', is_active=True)

    if request.method == 'POST':
        if 'create_asset' in request.POST:
            asset_code = request.POST.get('asset_code')
            name = request.POST.get('name')
            category = request.POST.get('category')
            purchase_date = request.POST.get('purchase_date')
            purchase_cost = Decimal(request.POST.get('purchase_cost') or '0')
            residual_value = Decimal(request.POST.get('residual_value') or '0')
            depreciation_method = request.POST.get('depreciation_method')
            useful_life_years = int(request.POST.get('useful_life_years') or '5')
            depreciation_rate = Decimal(request.POST.get('depreciation_rate') or '0')
            asset_acc_id = request.POST.get('asset_account_id')
            dep_acc_id = request.POST.get('depreciation_account_id')
            accum_acc_id = request.POST.get('accumulated_dep_account_id')

            try:
                asset_account = ChartOfAccounts.objects.get(id=asset_acc_id)
                depreciation_account = ChartOfAccounts.objects.get(id=dep_acc_id) if dep_acc_id else None
                accumulated_dep_account = ChartOfAccounts.objects.get(id=accum_acc_id) if accum_acc_id else None

                FixedAsset.objects.create(
                    asset_code=asset_code,
                    name=name,
                    category=category,
                    purchase_date=purchase_date,
                    purchase_cost=purchase_cost,
                    residual_value=residual_value,
                    depreciation_method=depreciation_method,
                    useful_life_years=useful_life_years,
                    depreciation_rate=depreciation_rate,
                    asset_account=asset_account,
                    depreciation_account=depreciation_account,
                    accumulated_dep_account=accumulated_dep_account,
                    created_by=request.user
                )
                messages.success(request, f"Asset {asset_code} - {name} added to register.")
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")
            return redirect('fixed_assets_list')

    return render(request, 'erp_core/financials/fixed_assets.html', {
        'assets': assets,
        'asset_accounts': asset_accounts,
        'dep_accounts': dep_accounts,
        'accum_accounts': accum_accounts,
    })

@login_required
def run_depreciation(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        date_str = request.POST.get('run_date')
        if date_str:
            try:
                run_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
                period = AccountingService.get_or_create_period(run_date)
                
                assets = FixedAsset.objects.filter(status='ACTIVE')
                depreciated_count = 0

                with transaction.atomic():
                    for asset in assets:
                        if DepreciationSchedule.objects.filter(asset=asset, period=period).exists():
                            continue
                        
                        monthly_dep = asset.monthly_depreciation
                        if monthly_dep <= 0:
                            continue

                        journal = AccountingService.post_depreciation(asset, period, request.user)
                        if journal:
                            DepreciationSchedule.objects.create(
                                asset=asset,
                                period=period,
                                depreciation_amount=monthly_dep,
                                accumulated_depreciation=asset.accumulated_depreciation,
                                net_book_value=asset.net_book_value,
                                journal_entry=journal,
                                posted=True
                            )
                            depreciated_count += 1
                
                messages.success(request, f"Depreciation complete. Calculated depreciation for {depreciated_count} assets.")
            except Exception as e:
                messages.error(request, f"Error running depreciation: {str(e)}")

    return redirect('fixed_assets_list')

@login_required
def bank_reconciliation_list(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    reconciliations = BankReconciliation.objects.all().order_by('-period_end')
    bank_accounts = BankAccount.objects.filter(is_active=True)

    if request.method == 'POST':
        bank_acc_id = request.POST.get('bank_account_id')
        start_date = request.POST.get('period_start')
        end_date = request.POST.get('period_end')
        stmt_open = Decimal(request.POST.get('stmt_opening') or '0')
        stmt_close = Decimal(request.POST.get('stmt_closing') or '0')

        try:
            bank_account = BankAccount.objects.get(id=bank_acc_id)
            
            gl_acc = bank_account.gl_account.first()
            book_open = gl_acc.get_balance_at_date(timezone.datetime.strptime(start_date, '%Y-%m-%d').date()) if gl_acc else Decimal('0')
            book_close = gl_acc.get_balance_at_date(timezone.datetime.strptime(end_date, '%Y-%m-%d').date()) if gl_acc else Decimal('0')

            recon = BankReconciliation.objects.create(
                bank_account=bank_account,
                period_start=start_date,
                period_end=end_date,
                statement_opening_balance=stmt_open,
                statement_closing_balance=stmt_close,
                book_opening_balance=book_open,
                book_closing_balance=book_close,
                prepared_by=request.user,
                status='DRAFT'
            )
            messages.success(request, f"Reconciliation {recon.reference} prepared for {recon.period_start} to {recon.period_end}")
            return redirect('bank_reconciliation_detail', recon_id=recon.id)
        except Exception as e:
            messages.error(request, f"Error preparing reconciliation: {str(e)}")

    return render(request, 'erp_core/financials/bank_reconciliation_list.html', {
        'reconciliations': reconciliations,
        'bank_accounts': bank_accounts,
    })

@login_required
def bank_reconciliation_detail(request, recon_id):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    recon = BankReconciliation.objects.get(id=recon_id)
    
    unmatched_stmt = BankTransaction.objects.filter(
        bank_account=recon.bank_account,
        is_reconciled=False,
        transaction_date__lte=recon.period_end
    )
    
    gl_acc = recon.bank_account.gl_account.first()
    unreconciled_book = JournalEntryLine.objects.filter(
        account=gl_acc,
        journal__status='POSTED',
        bank_transaction__isnull=True,
        journal__posting_date__lte=recon.period_end
    ) if gl_acc else []

    if request.method == 'POST':
        if 'finalize' in request.POST:
            recon.status = 'COMPLETED'
            recon.save()
            
            bank = recon.bank_account
            bank.last_reconciled_date = recon.period_end
            bank.last_reconciled_balance = recon.statement_closing_balance
            bank.save()

            messages.success(request, f"Reconciliation {recon.reference} finalized.")
            return redirect('bank_reconciliation_list')

    return render(request, 'erp_core/financials/bank_reconciliation_detail.html', {
        'recon': recon,
        'unmatched_stmt': unmatched_stmt,
        'unreconciled_book': unreconciled_book,
    })

@login_required
def bank_reconciliation_match(request, recon_id):
    if request.method == 'POST':
        stmt_id = request.POST.get('stmt_id')
        book_line_id = request.POST.get('book_line_id')

        try:
            stmt = BankTransaction.objects.get(id=stmt_id)
            book_line = JournalEntryLine.objects.get(id=book_line_id)

            stmt.matched_journal_line = book_line
            stmt.is_reconciled = True
            stmt.status = 'RECONCILED'
            stmt.save()

            book_line.bank_transaction = stmt
            book_line.save()

            recon = BankReconciliation.objects.get(id=recon_id)
            stmt.reconciliation = recon
            stmt.save()

            gl_acc = recon.bank_account.gl_account.first()
            unmatched_lines = JournalEntryLine.objects.filter(
                account=gl_acc,
                journal__status='POSTED',
                bank_transaction__isnull=True,
                journal__posting_date__lte=recon.period_end
            )
            recon.deposits_in_transit = unmatched_lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            recon.outstanding_checks = unmatched_lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')
            recon.save()

            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def financial_reports(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    today = timezone.now().date()
    start_date = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
    end_date = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
    as_of_date = request.GET.get('as_of_date', today.strftime('%Y-%m-%d'))

    start_d = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
    end_d = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
    as_of_d = timezone.datetime.strptime(as_of_date, '%Y-%m-%d').date()

    trial_balance = TrialBalanceService.get_trial_balance(as_of_d)
    profit_loss = TrialBalanceService.get_profit_and_loss(start_d, end_d)
    balance_sheet = TrialBalanceService.get_balance_sheet(as_of_d)

    fiscal_year = FiscalYear.get_active()
    budget_lines = []
    if fiscal_year:
        for bl in fiscal_year.budget_lines.all():
            actual = bl.account.get_balance_at_date(end_d)
            budget_lines.append({
                'account': bl.account,
                'budget': bl.annual_budget,
                'actual': actual,
                'variance': bl.annual_budget - actual,
            })

    return render(request, 'erp_core/financials/financial_reports.html', {
        'start_date': start_date,
        'end_date': end_date,
        'as_of_date': as_of_date,
        'trial_balance': trial_balance,
        'profit_loss': profit_loss,
        'balance_sheet': balance_sheet,
        'budget_lines': budget_lines,
    })
