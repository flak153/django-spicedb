"""Management command to set up demo data for testing the UI."""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from django_rebac.models import HierarchyTypeDefinition, HierarchyNode, HierarchyNodeRole
from example_project.documents.models import Company


User = get_user_model()


class Command(BaseCommand):
    help = "Set up demo data for testing the hierarchy UI"

    def handle(self, *args, **options):
        # Create or get demo user
        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True},
        )
        if created:
            admin_user.set_password("admin")
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created admin user: admin/admin"))
        else:
            self.stdout.write("Admin user already exists")

        # Create some regular users
        users = []
        for name, email in [
            ("alice", "alice@example.com"),
            ("bob", "bob@example.com"),
            ("charlie", "charlie@example.com"),
            ("diana", "diana@example.com"),
        ]:
            user, created = User.objects.get_or_create(
                username=name,
                defaults={"email": email},
            )
            if created:
                user.set_password(name)
                user.save()
                self.stdout.write(f"Created user: {name}/{name}")
            users.append(user)

        # Create tenant (Company)
        tenant, created = Company.objects.get_or_create(
            slug="acme",
            defaults={"name": "Acme Corp"},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created tenant: {tenant.name}"))

        # Get content type for Company
        company_ct = ContentType.objects.get_for_model(Company)

        # Create hierarchy types
        org_type, _ = HierarchyTypeDefinition.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="organization",
            defaults={
                "name": "organization",
                "display_name": "Organization",
                "level": 0,
            },
        )

        dept_type, _ = HierarchyTypeDefinition.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="department",
            defaults={
                "name": "department",
                "display_name": "Department",
                "level": 1,
                "parent_type": org_type,
            },
        )

        team_type, _ = HierarchyTypeDefinition.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="team",
            defaults={
                "name": "team",
                "display_name": "Team",
                "level": 2,
                "parent_type": dept_type,
            },
        )

        self.stdout.write("Created hierarchy types: organization, department, team")

        # Create hierarchy nodes
        org, _ = HierarchyNode.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="acme-hq",
            defaults={
                "hierarchy_type": org_type,
                "name": "Acme Corp HQ",
            },
        )

        engineering, _ = HierarchyNode.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="engineering",
            defaults={
                "hierarchy_type": dept_type,
                "parent": org,
                "name": "Engineering",
            },
        )

        sales, _ = HierarchyNode.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="sales",
            defaults={
                "hierarchy_type": dept_type,
                "parent": org,
                "name": "Sales",
            },
        )

        backend_team, _ = HierarchyNode.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="backend",
            defaults={
                "hierarchy_type": team_type,
                "parent": engineering,
                "name": "Backend Team",
            },
        )

        frontend_team, _ = HierarchyNode.objects.get_or_create(
            tenant_content_type=company_ct,
            tenant_object_id=str(tenant.pk),
            slug="frontend",
            defaults={
                "hierarchy_type": team_type,
                "parent": engineering,
                "name": "Frontend Team",
            },
        )

        self.stdout.write("Created hierarchy nodes")

        # Assign roles
        alice, bob, charlie, diana = users

        # Alice is org owner
        HierarchyNodeRole.objects.get_or_create(
            node=org,
            user=alice,
            defaults={"role": "owner", "inheritable": True},
        )

        # Bob manages engineering
        HierarchyNodeRole.objects.get_or_create(
            node=engineering,
            user=bob,
            defaults={"role": "manager", "inheritable": True},
        )

        # Charlie leads backend team
        HierarchyNodeRole.objects.get_or_create(
            node=backend_team,
            user=charlie,
            defaults={"role": "lead", "inheritable": False},
        )

        # Diana is a member of frontend team
        HierarchyNodeRole.objects.get_or_create(
            node=frontend_team,
            user=diana,
            defaults={"role": "member", "inheritable": False},
        )

        self.stdout.write(self.style.SUCCESS("\nDemo data setup complete!"))
        self.stdout.write(f"\nAccess the UI at: http://localhost:8000/rebac/{tenant.pk}/hierarchy/")
        self.stdout.write("\nTest users:")
        self.stdout.write("  - admin/admin (superuser)")
        self.stdout.write("  - alice/alice (org owner)")
        self.stdout.write("  - bob/bob (engineering manager)")
        self.stdout.write("  - charlie/charlie (backend lead)")
        self.stdout.write("  - diana/diana (frontend member)")
