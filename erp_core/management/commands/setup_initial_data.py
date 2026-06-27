from django.core.management.base import BaseCommand
from django.db import transaction
from erp_core.models import (
    Role, CustomUser, Section, Class, StudentProfile, ParentProfile, 
    StaffProfile, FeeStructure, StaffSalaryConfig, Subject
)
from django.utils import timezone

class Command(BaseCommand):
    help = 'Seeds complete test and production data for the School ERP'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('Purging old user/class structures for clean seed...')
        # Clear existing class structure and users to avoid unique/integrity errors
        Class.objects.all().delete()
        Section.objects.all().delete()
        CustomUser.objects.all().delete()

        # 1. Create Roles
        self.stdout.write('Creating roles...')
        roles_to_create = [
            ('R01', 'Director'),
            ('R02', 'Principal'),
            ('R03', 'Accountant'),
            ('R04', 'Head of Section'),
            ('R05', 'Dean'),
            ('R06', 'Teacher'),
            ('R07', 'Student'),
            ('R08', 'Parent / Guardian'),
        ]

        roles_map = {}
        for code, name in roles_to_create:
            role, created = Role.objects.get_or_create(code=code, defaults={'name': name})
            roles_map[code] = role

        # 2. Create Admin Users
        self.stdout.write('Creating admin & management users...')
        
        # Director
        director_user = CustomUser.objects.create_user(
            username='LISdirector',
            email='director@leaders.ac.tz',
            first_name='Director',
            last_name='User',
            is_temporary_password=False
        )
        director_user.set_password('Password123')
        director_user.roles.add(roles_map['R01'])
        director_user.save()
        
        # Principal
        principal_user = CustomUser.objects.create_user(
            username='LISprincipal',
            email='principal@leaders.ac.tz',
            first_name='Principal',
            last_name='User',
            is_temporary_password=False
        )
        principal_user.set_password('Password123')
        principal_user.roles.add(roles_map['R02'])
        principal_user.save()
        
        # Accountant
        accountant_user = CustomUser.objects.create_user(
            username='accountant',
            email='accountant@leaders.ac.tz',
            first_name='Accountant',
            last_name='User',
            is_temporary_password=False
        )
        accountant_user.set_password('Password123')
        accountant_user.roles.add(roles_map['R03'])
        accountant_user.save()
        
        StaffSalaryConfig.objects.create(
            staff=accountant_user,
            basic_pay=1500000,
            housing_allowance=300000,
            transport_allowance=150000
        )

        # 3. Create 7 Teachers with varying salaries
        self.stdout.write('Creating 7 teachers with salary configs...')
        teachers = []
        base_basic_pay = 800000
        for i in range(1, 8):
            t_user = CustomUser.objects.create_user(
                username=f'teacher{i}',
                email=f'teacher{i}@leaders.ac.tz',
                first_name=f'Teacher{i}',
                last_name='Staff',
                is_temporary_password=False
            )
            t_user.set_password('Password123')
            t_user.roles.add(roles_map['R06'])
            t_user.save()
            teachers.append(t_user)

            # Create varying salaries
            basic = base_basic_pay + (i * 100000) # 900,000 to 1,500,000
            StaffSalaryConfig.objects.create(
                staff=t_user,
                basic_pay=basic,
                housing_allowance=200000,
                transport_allowance=100000
            )

        # 4. Sections & Classes
        self.stdout.write('Creating academic sections & classes...')
        ey_section = Section.objects.create(name='Early Years', head_of_section=principal_user)
        pri_section = Section.objects.create(name='Primary School', head_of_section=principal_user)

        # Map classes with assigned teachers
        baby_class = Class.objects.create(name='Baby Class', section=ey_section, class_teacher=teachers[0], level_type='EARLY_YEARS')
        nursery_class = Class.objects.create(name='Nursery', section=ey_section, class_teacher=teachers[1], level_type='EARLY_YEARS')
        reception_class = Class.objects.create(name='Reception', section=ey_section, class_teacher=teachers[2], level_type='EARLY_YEARS')
        year_1 = Class.objects.create(name='Year 1', section=pri_section, class_teacher=teachers[3], level_type='PRIMARY_LOWER')
        year_2 = Class.objects.create(name='Year 2', section=pri_section, class_teacher=teachers[4], level_type='PRIMARY_LOWER')

        # 5. Create default subjects & learning areas
        self.stdout.write('Creating subjects & learning areas...')
        Subject.objects.get_or_create(name='General', defaults={'level': 'PRIMARY_LOWER'})
        Subject.objects.create(name='Number Work', level='EARLY_YEARS')
        Subject.objects.create(name='Psychomotor Skills', level='EARLY_YEARS')
        Subject.objects.create(name='Mathematics', level='PRIMARY_LOWER')
        Subject.objects.create(name='English Language', level='PRIMARY_LOWER')

        # 6. Seed Students & Parents
        # babyclass 11 learners
        # nursery 13 learners
        # reception 12 learners
        # year 1 10 learners
        # year 2 7 learners
        # Total learners = 53
        student_cohorts = [
            (baby_class, 11, 'BC'),
            (nursery_class, 13, 'NC'),
            (reception_class, 12, 'RC'),
            (year_1, 10, 'Y1'),
            (year_2, 7, 'Y2'),
        ]

        self.stdout.write('Seeding students and assigning exactly 2 parents per student...')
        student_counter = 1
        for class_obj, count, prefix in student_cohorts:
            for j in range(1, count + 1):
                # Create Student User
                s_username = f'student_{prefix.lower()}_{j}'
                s_user = CustomUser.objects.create_user(
                    username=s_username,
                    email=f'{s_username}@leaders.ac.tz',
                    first_name=f'{prefix} Student',
                    last_name=str(j),
                    is_temporary_password=False
                )
                s_user.set_password('Password123')
                s_user.roles.add(roles_map['R07'])
                s_user.save()

                student_profile = StudentProfile.objects.create(
                    user=s_user,
                    student_id=f'LIS/STUD/2026/{student_counter:04d}',
                    current_class=class_obj
                )
                student_counter += 1

                # Create exactly 2 parents
                parent_a_user = CustomUser.objects.create_user(
                    username=f'parent_{s_username}_a',
                    email=f'parent_{s_username}_a@gmail.com',
                    first_name=f'ParentA_{prefix}',
                    last_name=str(j),
                    is_temporary_password=False
                )
                parent_a_user.set_password('Password123')
                parent_a_user.roles.add(roles_map['R08'])
                parent_a_user.save()

                parent_b_user = CustomUser.objects.create_user(
                    username=f'parent_{s_username}_b',
                    email=f'parent_{s_username}_b@gmail.com',
                    first_name=f'ParentB_{prefix}',
                    last_name=str(j),
                    is_temporary_password=False
                )
                parent_b_user.set_password('Password123')
                parent_b_user.roles.add(roles_map['R08'])
                parent_b_user.save()

                p_profile_a = ParentProfile.objects.create(user=parent_a_user)
                p_profile_a.students.add(student_profile)

                p_profile_b = ParentProfile.objects.create(user=parent_b_user)
                p_profile_b.students.add(student_profile)

        # 7. Fee Structures
        # Baby Class: 7,000,000
        # Nursery: 7,000,000
        # Reception: 9,000,000
        # Year 1: 10,000,000
        # Year 2: 10,000,000
        self.stdout.write('Configuring school fee structures per class...')
        fee_mapping = [
            (baby_class, 5000000, 1000000, 1000000),
            (nursery_class, 5000000, 1000000, 1000000),
            (reception_class, 6000000, 1500000, 1500000),
            (year_1, 7000000, 1500000, 1500000),
            (year_2, 7000000, 1500000, 1500000),
        ]

        for class_obj, tuition, lunch, transport in fee_mapping:
            # Tuition
            FeeStructure.objects.create(
                class_obj=class_obj,
                vote_head='Tuition Fee',
                amount=tuition,
                year='2026',
                billing_mode='TERMLY',
                due_term='Term 1'
            )
            # Lunch
            FeeStructure.objects.create(
                class_obj=class_obj,
                vote_head='Lunch Fee',
                amount=lunch,
                year='2026',
                billing_mode='TERMLY',
                due_term='Term 1'
            )
            # Transport
            FeeStructure.objects.create(
                class_obj=class_obj,
                vote_head='Transport Fee',
                amount=transport,
                year='2026',
                billing_mode='TERMLY',
                due_term='Term 1'
            )
            # Admission (once a year one time lifetime)
            FeeStructure.objects.create(
                class_obj=class_obj,
                vote_head='Admission Fee',
                amount=100000,
                year='2026',
                billing_mode='LIFETIME',
                is_one_time=True
            )
            # Uniform (once a year one time lifetime)
            FeeStructure.objects.create(
                class_obj=class_obj,
                vote_head='Uniform Fee',
                amount=80000,
                year='2026',
                billing_mode='LIFETIME',
                is_one_time=True
            )

        self.stdout.write(self.style.SUCCESS('Whole school initial data seeded successfully!'))
