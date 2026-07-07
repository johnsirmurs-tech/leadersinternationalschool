from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
import json
import random

from .models import CustomUser, Role, Class
from .models_syllabus import (
    CambridgeStage, CambridgeSubject, SyllabusUnit,
    SyllabusTopic, SyllabusLearningObjective
)
from .models_quiz import (
    Quiz, QuizBank, QuizQuestion, QuizAttempt,
    StudentAnswer, AIGenerationJob
)
from .ai_quiz_service import QuizGenerationOrchestrator


@login_required
def quiz_builder(request):
    """Teacher wizard to generate AI questions or build a quiz."""
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Only teachers and admins can build quizzes.")
        return redirect('dashboard')

    subjects = CambridgeSubject.objects.filter(is_active=True)
    stages = CambridgeStage.objects.filter(is_active=True)
    classes = Class.objects.all()

    # Retrieve units/topics via AJAX if requested
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        subject_id = request.GET.get('subject_id')
        stage_id = request.GET.get('stage_id')
        unit_id = request.GET.get('unit_id')

        if subject_id and stage_id and not unit_id:
            units = SyllabusUnit.objects.filter(subject_id=subject_id, stage_id=stage_id)
            return JsonResponse({
                'units': [{'id': u.id, 'code': u.code, 'title': u.title} for u in units]
            })
        elif unit_id:
            topics = SyllabusTopic.objects.filter(unit_id=unit_id, is_active=True)
            return JsonResponse({
                'topics': [{'id': t.id, 'title': t.title} for t in topics]
            })

    if request.method == 'POST':
        subject_id = request.POST.get('subject')
        stage_id = request.POST.get('stage')
        unit_id = request.POST.get('unit')
        topic_ids = request.POST.getlist('topics')
        difficulty = request.POST.get('difficulty')
        num_questions = int(request.POST.get('num_questions', 5))

        try:
            res = QuizGenerationOrchestrator.initiate_generation(
                user=request.user,
                subject_id=subject_id,
                stage_id=stage_id,
                topic_ids=topic_ids,
                difficulty=difficulty,
                num_questions=num_questions,
                unit_id=unit_id if unit_id else None
            )
            messages.success(request, f"Successfully initiated quiz generation job.")
            return redirect('review_questions', job_id=res['job_id'])
        except Exception as e:
            messages.error(request, f"Quiz generation failed: {str(e)}")

    return render(request, 'erp_core/academics/quiz_builder.html', {
        'subjects': subjects,
        'stages': stages,
        'classes': classes,
    })


@login_required
def review_questions(request, job_id):
    """Teacher interface to review AI-generated questions before approving."""
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    job = get_object_or_404(AIGenerationJob, id=job_id)
    questions = job.generated_questions.all()

    if request.method == 'POST':
        # Accept/edit or reject questions
        action = request.POST.get('action')
        if action == 'approve_all':
            questions.update(status='APPROVED')
            
            # Create a Quiz out of approved questions
            quiz = Quiz.objects.create(
                title=f"AI Generated Quiz - {job.subject.name} ({job.stage.name})",
                subject=job.subject,
                stage=job.stage,
                unit=job.unit,
                difficulty=job.difficulty,
                total_questions=questions.count(),
                created_by=request.user,
                status='DRAFT',
                ai_generated=True
            )
            quiz.topics.set(job.topics.all())
            
            for idx, q in enumerate(questions):
                QuizQuestion.objects.create(
                    quiz=quiz,
                    question=q,
                    order=idx,
                    marks=1
                )

            messages.success(request, "All questions approved. Draft quiz created.")
            return redirect('assign_quiz', quiz_id=quiz.id)
            
        elif action == 'save_question':
            q_id = request.POST.get('question_id')
            q = get_object_or_404(QuizBank, id=q_id)
            q.question_text = request.POST.get('question_text')
            q.option_a = request.POST.get('option_a')
            q.option_b = request.POST.get('option_b')
            q.option_c = request.POST.get('option_c')
            q.option_d = request.POST.get('option_d')
            q.correct_answer = request.POST.get('correct_answer')
            q.explanation = request.POST.get('explanation')
            q.status = 'APPROVED'
            q.save()
            return JsonResponse({'status': 'success'})

    return render(request, 'erp_core/academics/review_questions.html', {
        'job': job,
        'questions': questions,
    })


@login_required
def assign_quiz(request, quiz_id):
    """Assign quiz to class or individual students."""
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R06' not in role_codes and 'R01' not in role_codes and 'R02' not in role_codes:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    quiz = get_object_or_404(Quiz, id=quiz_id)
    classes = Class.objects.all()

    if request.method == 'POST':
        assignment_type = request.POST.get('assignment_type')
        class_id = request.POST.get('assigned_class_id')
        time_limit = request.POST.get('time_limit_minutes')
        passing_score = request.POST.get('passing_score', 50)
        
        quiz.assignment_type = assignment_type
        if assignment_type == 'CLASS' and class_id:
            quiz.assigned_class = Class.objects.get(id=class_id)
        
        if time_limit:
            quiz.time_limit_minutes = int(time_limit)
        
        quiz.passing_score = int(passing_score)
        quiz.status = 'PUBLISHED'
        quiz.published_at = timezone.now()
        quiz.save()
        
        messages.success(request, f"Quiz '{quiz.title}' assigned successfully.")
        return redirect('dashboard')

    return render(request, 'erp_core/academics/assign_quiz.html', {
        'quiz': quiz,
        'classes': classes,
    })


# ─── STUDENT: QUIZ PORTAL ─────────────────────────────────────────────────────

@login_required
def student_quizzes(request):
    """Displays quizzes assigned to the logged in student."""
    role_codes = [role.code for role in request.user.roles.all()]
    if 'R07' not in role_codes:
        messages.error(request, "Only students can access this portal.")
        return redirect('dashboard')

    # Find quizzes assigned to student's class
    student_profile = getattr(request.user, 'student_profile', None)
    if not student_profile or not student_profile.current_class:
        messages.error(request, "You are not assigned to a class.")
        return redirect('dashboard')

    quizzes = Quiz.objects.filter(
        assigned_class=student_profile.current_class,
        status='PUBLISHED'
    )

    attempts = QuizAttempt.objects.filter(student=request.user)
    completed_quiz_ids = attempts.filter(status='COMPLETED').values_list('quiz_id', flat=True)

    return render(request, 'erp_core/academics/student_quizzes.html', {
        'quizzes': quizzes,
        'completed_quiz_ids': completed_quiz_ids,
        'attempts': attempts,
    })


@login_required
@transaction.atomic
def take_quiz(request, quiz_id):
    """Interface for student to sit the multiple-choice quiz."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    student_profile = getattr(request.user, 'student_profile', None)
    
    if not student_profile or quiz.assigned_class != student_profile.current_class:
        messages.error(request, "This quiz is not assigned to your class.")
        return redirect('dashboard')

    # Retrieve or start attempt
    attempt, created = QuizAttempt.objects.get_or_create(
        quiz=quiz,
        student=request.user,
        defaults={
            'status': 'IN_PROGRESS',
            'question_order': [str(q.id) for q in quiz.questions.all()]
        }
    )

    if attempt.status == 'COMPLETED':
        messages.warning(request, "You have already completed this quiz.")
        return redirect('quiz_attempt_result', attempt_id=attempt.id)

    # Calculate remaining time
    time_limit = quiz.time_limit_minutes
    elapsed = (timezone.now() - attempt.started_at).total_seconds()
    remaining_seconds = (time_limit * 60) - elapsed if time_limit else None

    if remaining_seconds is not None and remaining_seconds <= 0:
        # Auto-grade and complete on timeout
        attempt.calculate_score()
        messages.info(request, "Quiz time limit reached. Auto-submitted.")
        return redirect('quiz_attempt_result', attempt_id=attempt.id)

    questions = quiz.quiz_questions.all().order_by('order')

    if request.method == 'POST':
        # Process submissions
        for qq in questions:
            ans_val = request.POST.get(f'question_{qq.question.id}')
            if ans_val:
                StudentAnswer.objects.update_or_create(
                    attempt=attempt,
                    quiz_question=qq,
                    defaults={
                        'question': qq.question,
                        'selected_option': ans_val
                    }
                )
        
        # Mark attempt as completed
        attempt.calculate_score()
        messages.success(request, "Quiz submitted successfully!")
        return redirect('quiz_attempt_result', attempt_id=attempt.id)

    return render(request, 'erp_core/academics/take_quiz.html', {
        'quiz': quiz,
        'attempt': attempt,
        'questions': questions,
        'remaining_seconds': int(remaining_seconds) if remaining_seconds else None,
    })


@login_required
def quiz_attempt_result(request, attempt_id):
    """Show student attempt details and auto-grade score breakdown."""
    attempt = get_object_or_404(QuizAttempt, id=attempt_id)
    
    # Authorize: student who took it, or teacher/admin
    role_codes = [role.code for role in request.user.roles.all()]
    is_authorized = (
        attempt.student == request.user or
        'R06' in role_codes or
        'R01' in role_codes or
        'R02' in role_codes
    )
    if not is_authorized:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')

    answers = attempt.answers.all().prefetch_related('question')

    return render(request, 'erp_core/academics/quiz_results.html', {
        'attempt': attempt,
        'answers': answers,
    })
