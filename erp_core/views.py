from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import CustomUser, Role, GradeBoundary, LearningAreaProgress, RawMark, LessonPlan, AutoGradedActivity, ActivityQuestion, StudentActivitySubmission, Class, StudentProfile, FeeStructure, FeePayment, StaffSalaryConfig, StaffAllowance, StaffDeduction, Payroll, Payslip, PayslipLineItem, Expense, Subject, TeacherSubjectAssignment, StudentAttendance
from django.http import HttpResponse
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def custom_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        if not username_or_email or not password:
            messages.error(request, "Please enter both username/email and password.")
            return render(request, 'erp_core/login.html')

        # Find user by username or email
        user = None
        try:
            if '@' in username_or_email:
                user = CustomUser.objects.get(email=username_or_email)
            else:
                user = CustomUser.objects.get(username=username_or_email)
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

    user = request.user
    roles = user.roles.all()
    
    # Merge permissions or direct to specific dashboard view based on user roles
    context = {
        'roles': roles,
        'user': user
    }
    
    # Check roles and render the appropriate template
    role_codes = [role.code for role in roles]
    
    # Director has highest authority
    if 'R01' in role_codes:
        return render(request, 'erp_core/dashboards/director.html', context)
    elif 'R02' in role_codes:
        return render(request, 'erp_core/dashboards/principal.html', context)
    elif 'R03' in role_codes:
        return render(request, 'erp_core/dashboards/accountant.html', context)
    elif 'R04' in role_codes:
        return render(request, 'erp_core/dashboards/head_of_section.html', context)
    elif 'R05' in role_codes:
        return render(request, 'erp_core/dashboards/dean.html', context)
    elif 'R06' in role_codes:
        return render(request, 'erp_core/dashboards/teacher.html', context)
    elif 'R07' in role_codes:
        return render(request, 'erp_core/dashboards/student.html', context)
    elif 'R08' in role_codes:
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

    return render(request, 'erp_core/academics/lesson_plan_form.html', {'classes': classes})

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
                    FeePayment.objects.create(
                        student=student,
                        fee_structure=fs,
                        amount_paid=amount,
                        payment_method=payment_method,
                        receipt_number=receipt_no,
                        notes=notes,
                        recorded_by=request.user
                    )

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

    student_balances = []
    students = StudentProfile.objects.all()

    for student in students:
        # Sum total fee due for student's class
        total_due = FeeStructure.objects.filter(class_obj=student.current_class).aggregate(Sum('amount'))['amount__sum'] or 0
        # Sum payments made by student
        total_paid = FeePayment.objects.filter(student=student).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        balance = total_due - total_paid

        if balance <= 0:
            status = 'PAID'
        elif total_paid > 0:
            status = 'PARTIAL'
        else:
            status = 'UNPAID'

        student_balances.append({
            'student': student,
            'total_due': total_due,
            'total_paid': total_paid,
            'balance': balance,
            'status': status
        })

    if request.method == 'POST' and request.POST.get('action') == 'send_reminder':
        student_ids = request.POST.getlist('student_ids')
        if student_ids:
            messages.success(request, f"Fee reminders successfully sent to parents of {len(student_ids)} students.")
            return redirect('fee_balances')

    return render(request, 'erp_core/financials/fee_balances.html', {
        'student_balances': student_balances
    })

@login_required
def salary_setup(request):
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R03' not in role_codes and 'R01' not in role_codes:
        messages.error(request, "Only Accountant or Director can access salary configurations.")
        return redirect('dashboard')

    # Exclude students and parents
    staff_members = CustomUser.objects.exclude(roles__code__in=['R07', 'R08']).distinct()
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
            nssf = request.POST.get('nssf_deduction', 0)
            paye = request.POST.get('paye_tax', 0)

            salary_config.basic_pay = float(basic_pay)
            salary_config.housing_allowance = float(housing)
            salary_config.transport_allowance = float(transport)
            salary_config.nssf_deduction = float(nssf)
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
                deductions_total = cfg.nssf_deduction + cfg.paye_tax + (custom_deductions.aggregate(Sum('amount'))['amount__sum'] or 0)
                
                gross = cfg.basic_pay + cfg.housing_allowance + cfg.transport_allowance + (custom_allowances.aggregate(Sum('amount'))['amount__sum'] or 0)
                net = gross - deductions_total

                payslip = Payslip.objects.create(
                    payroll=payroll,
                    staff=s,
                    basic_pay=cfg.basic_pay,
                    housing_allowance=cfg.housing_allowance,
                    transport_allowance=cfg.transport_allowance,
                    nssf_deduction=cfg.nssf_deduction,
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

        # Update payslip statuses
        payroll.payslips.filter(status='PENDING').update(status='FINALIZED')

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
                Expense.objects.create(
                    category=category,
                    description=description,
                    amount=float(amount),
                    paid_to=paid_to,
                    payment_method=payment_method,
                    reference_number=reference_number,
                    receipt_attached=receipt_attached,
                    recorded_by=request.user
                )
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
    students = []
    attendances = {}

    if selected_class_id:
        selected_class = Class.objects.get(id=selected_class_id)
        
        # Enforce Class Teacher constraint
        if 'R06' in role_codes and not is_admin:
            if selected_class.class_teacher != user:
                messages.error(request, f"You are not assigned as the class teacher for {selected_class.name}. Only class teachers can manage attendance.")
                return redirect('attendance_registry')

        students = StudentProfile.objects.filter(current_class=selected_class).order_by('user__first_name')
        existing = StudentAttendance.objects.filter(student__current_class=selected_class, date=selected_date)
        for att in existing:
            attendances[att.student.id] = att.status

    return render(request, 'erp_core/administration/attendance.html', {
        'classes': classes,
        'selected_class': selected_class,
        'selected_date': selected_date,
        'students': students,
        'attendances': attendances,
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
