from django.core.management.base import BaseCommand
from erp_core.models import Role, CustomUser
from django.contrib.auth.models import Group

class Command(BaseCommand):
    help = 'Sets up initial roles and default test users for the School ERP'

    def handle(self, *args, **options):
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
            if created:
                self.stdout.write(f'  Created role: {name}')

        # 2. Create Users
        self.stdout.write('Creating test users...')
        test_users = [
            ('director', 'director@leaders.ac.tz', 'Director', 'User', ['R01'], False),
            ('principal', 'principal@leaders.ac.tz', 'Principal', 'User', ['R02'], False),
            ('accountant', 'accountant@leaders.ac.tz', 'Accountant', 'User', ['R03'], False),
            ('teacher', 'teacher@leaders.ac.tz', 'Teacher', 'User', ['R06'], False),
            ('student', 'student@leaders.ac.tz', 'Student', 'User', ['R07'], False),
            ('parent', 'parent@leaders.ac.tz', 'Parent', 'User', ['R08'], False),
            # User with temporary password for testing redirect flow
            ('tempuser', 'temp@leaders.ac.tz', 'New', 'Staff Member', ['R06'], True),
        ]

        for username, email, first_name, last_name, role_codes, is_temp in test_users:
            user, created = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'is_temporary_password': is_temp,
                    'is_staff': True,
                    'is_superuser': True if 'R01' in role_codes else False
                }
            )
            
            if created:
                user.set_password('Password123!')
                user.save()
                for code in role_codes:
                    user.roles.add(roles_map[code])
                self.stdout.write(f'  Created user "{username}" with password "Password123!"')
            else:
                self.stdout.write(f'  User "{username}" already exists.')

        # 3. Create Sections, Classes, and Profiles
        self.stdout.write('Creating school structure and student profiles...')
        from erp_core.models import Section, Class, StudentProfile
        
        # Sections
        ey_section, _ = Section.objects.get_or_create(name='Early Years')
        pri_section, _ = Section.objects.get_or_create(name='Primary School')

        # Classes
        teacher_user = CustomUser.objects.get(username='teacher')
        baby_class, _ = Class.objects.get_or_create(
            name='Baby Class',
            defaults={'section': ey_section, 'class_teacher': teacher_user, 'level_type': 'EARLY_YEARS'}
        )
        class_1a, _ = Class.objects.get_or_create(
            name='Class 1A',
            defaults={'section': pri_section, 'class_teacher': teacher_user, 'level_type': 'PRIMARY_LOWER'}
        )

        # Profiles
        student_user = CustomUser.objects.get(username='student')
        StudentProfile.objects.get_or_create(
            user=student_user,
            defaults={'student_id': 'LIS/STUD/2026/0001', 'current_class': baby_class}
        )

        # Map another student user for class 1a
        student2_user, created2 = CustomUser.objects.get_or_create(
            username='student2',
            defaults={
                'email': 'student2@leaders.ac.tz',
                'first_name': 'Amani',
                'last_name': 'Komba',
                'is_temporary_password': False
            }
        )
        if created2:
            student2_user.set_password('Password123!')
            student2_user.save()
            student2_user.roles.add(roles_map['R07'])
            
        StudentProfile.objects.get_or_create(
            user=student2_user,
            defaults={'student_id': 'LIS/STUD/2026/0002', 'current_class': class_1a}
        )

        self.stdout.write(self.style.SUCCESS('Initial setup completed successfully!'))
