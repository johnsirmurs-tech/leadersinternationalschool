from django.urls import path
from django.contrib.auth import views as auth_views
from . import views, views_quiz

urlpatterns = [
    path('', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('change-password/', views.change_temporary_password, name='change_temporary_password'),
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Password Reset Flow (using Django default views, but we will style their templates)
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='erp_core/registration/password_reset_form.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='erp_core/registration/password_reset_done.html'), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='erp_core/registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='erp_core/registration/password_reset_complete.html'), name='password_reset_complete'),

    # Phase 2 urls
    path('boundaries/', views.grade_boundaries, name='grade_boundaries'),
    path('early-years-progress/', views.early_years_progress, name='early_years_progress'),
    path('enter-raw-marks/', views.enter_raw_marks, name='enter_raw_marks'),
    path('lesson-plans/', views.lesson_plan_list, name='lesson_plan_list'),
    path('lesson-plans/create/', views.create_lesson_plan, name='create_lesson_plan'),
    path('lesson-plans/review/<int:plan_id>/', views.review_lesson_plan, name='review_lesson_plan'),
    path('lesson-plans/pdf/<int:plan_id>/', views.download_lesson_plan_pdf, name='download_lesson_plan_pdf'),
    path('activities/', views.activity_list, name='activity_list'),
    path('activities/create/', views.create_activity, name='create_activity'),
    path('activities/take/<int:activity_id>/', views.take_activity, name='take_activity'),
    path('auto-save-mark/', views.auto_save_mark, name='auto_save_mark'),
    path('publish-marks/', views.publish_and_lock_marks, name='publish_and_lock_marks'),

    # Phase 3 URLs
    path('financials/fees/setup/', views.fee_structure_setup, name='fee_structure_setup'),
    path('financials/fees/payment/', views.record_payment, name='record_payment'),
    path('financials/fees/payment/get-dues/<int:student_id>/', views.get_student_dues, name='get_student_dues'),
    path('financials/fees/payment/receipt/<str:receipt_no>/', views.view_receipt, name='view_receipt'),
    path('financials/fees/balances/', views.fee_balances, name='fee_balances'),
    path('financials/salaries/setup/', views.salary_setup, name='salary_setup'),
    path('financials/payroll/', views.payroll_list, name='payroll_list'),
    path('financials/payroll/finalize/<int:payroll_id>/', views.finalize_payroll, name='finalize_payroll'),
    path('financials/payslip/<int:payslip_id>/', views.view_payslip, name='view_payslip'),
    path('financials/payslip/edit/<int:payslip_id>/', views.edit_payslip, name='edit_payslip'),
    path('financials/expenses/', views.expense_list, name='expense_list'),

    # Phase 4 URLs
    path('administration/users/', views.user_list, name='user_list'),
    path('administration/users/create/', views.user_create, name='user_create'),
    path('administration/users/edit/<int:user_id>/', views.user_edit, name='user_edit'),
    path('administration/users/toggle/<int:user_id>/', views.user_toggle_status, name='user_toggle_status'),
    path('administration/users/change-password/<int:user_id>/', views.admin_change_password, name='admin_change_password'),
    path('administration/change-my-password/', views.change_my_password, name='change_my_password'),
    
    path('administration/subjects/', views.subject_setup, name='subject_setup'),
    path('administration/subjects/delete/<int:subject_id>/', views.subject_delete, name='subject_delete'),
    
    path('administration/assignments/', views.teacher_assignment_setup, name='teacher_assignment_setup'),
    path('administration/assignments/delete/<int:assignment_id>/', views.teacher_assignment_delete, name='teacher_assignment_delete'),
    
    path('attendance/', views.attendance_registry, name='attendance_registry'),
    path('attendance/save/', views.save_attendance, name='save_attendance'),
    
    path('academics/report-cards/', views.report_card_generator, name='report_card_generator'),
    path('academics/report-cards/view/<int:student_id>/<str:term>/<str:year>/', views.view_report_card, name='view_report_card'),
    
    path('financials/statements/', views.financial_statements, name='financial_statements'),

    # Stock Inventory
    path('inventory/', views.inventory_list, name='inventory_list'),
    path('inventory/create/', views.inventory_create, name='inventory_create'),
    path('inventory/update/<int:item_id>/', views.inventory_update, name='inventory_update'),
    path('inventory/movement/create/', views.stock_movement_create, name='stock_movement_create'),

    # Transport
    path('transport/', views.transport_list, name='transport_list'),
    path('transport/create/', views.transport_create, name='transport_create'),
    path('transport/assign/<int:student_id>/', views.transport_assign_student, name='transport_assign_student'),

    # Procurement Requisitions
    path('financials/procurement/', views.procurement_requisitions, name='procurement_requisitions'),

    # Biometric Integration
    path('api/biometric/push/', views.api_biometric_log_push, name='api_biometric_log_push'),
    path('administration/biometric/register/', views.biometric_registration, name='biometric_registration'),
    path('administration/biometric/dashboard/', views.biometric_dashboard, name='biometric_dashboard'),
    path('administration/biometric/exceptions/', views.attendance_exceptions, name='attendance_exceptions'),

    # Kitchen LED Display
    path('kitchen/led-display/', views.kitchen_led_display, name='kitchen_led_display'),
    path('api/kitchen/led-data/', views.kitchen_led_data_api, name='kitchen_led_data_api'),

    # Bank Integration
    path('api/bank/webhook/', views.bank_deposit_webhook, name='bank_deposit_webhook'),
    path('financials/fees/bank-deposits/', views.bank_deposits_list, name='bank_deposits_list'),
    path('financials/fees/bank-deposits/allocate/<int:deposit_id>/', views.allocate_bank_deposit, name='allocate_bank_deposit'),
    path('administration/integrations/', views.integration_settings, name='integration_settings'),

    # Accounting Module URLs
    path('financials/accounting/coa/', views.chart_of_accounts, name='chart_of_accounts'),
    path('financials/accounting/journals/', views.journal_entries_list, name='journal_entries_list'),
    path('financials/accounting/journals/post/<int:entry_id>/', views.post_journal_entry, name='post_journal_entry'),
    path('financials/accounting/journals/reverse/<int:entry_id>/', views.reverse_journal_entry, name='reverse_journal_entry'),
    path('financials/accounting/bills/', views.bills_list, name='bills_list'),
    path('financials/accounting/bills/pay/<int:bill_id>/', views.pay_bill, name='pay_bill'),
    path('financials/accounting/assets/', views.fixed_assets_list, name='fixed_assets_list'),
    path('financials/accounting/assets/depreciate/', views.run_depreciation, name='run_depreciation'),
    path('financials/accounting/recon/', views.bank_reconciliation_list, name='bank_reconciliation_list'),
    path('financials/accounting/recon/<int:recon_id>/', views.bank_reconciliation_detail, name='bank_reconciliation_detail'),
    path('financials/accounting/recon/match/<int:recon_id>/', views.bank_reconciliation_match, name='bank_reconciliation_match'),
    path('financials/accounting/reports/', views.financial_reports, name='financial_reports'),

    # Cambridge AI Quiz URLs
    path('academics/quiz/builder/', views_quiz.quiz_builder, name='quiz_builder'),
    path('academics/quiz/review/<uuid:job_id>/', views_quiz.review_questions, name='review_questions'),
    path('academics/quiz/assign/<uuid:quiz_id>/', views_quiz.assign_quiz, name='assign_quiz'),
    path('academics/quiz/portal/', views_quiz.student_quizzes, name='student_quizzes'),
    path('academics/quiz/take/<uuid:quiz_id>/', views_quiz.take_quiz, name='take_quiz'),
    path('academics/quiz/result/<uuid:attempt_id>/', views_quiz.quiz_attempt_result, name='quiz_attempt_result'),
]
