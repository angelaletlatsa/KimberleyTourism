from django.core.management.base import BaseCommand
from django.db.models import Avg, Count

from reviews.models import Review
from experiences.models import Experience
from guides.models import GuideProfile


class Command(BaseCommand):
    help = (
        "Recalculate average_rating and total_reviews for every "
        "experience and guide from approved reviews."
    )

    def handle(self, *args, **options):
        # ---------- EXPERIENCES ----------
        self.stdout.write(self.style.WARNING("Rebuilding experience ratings..."))

        exp_count = 0
        for exp in Experience.objects.all():
            stats = Review.objects.filter(
                experience=exp,
                review_type='experience',
                moderation_status='approved'
            ).aggregate(avg=Avg('rating'), total=Count('id'))

            exp.average_rating = stats['avg'] or 0
            exp.total_reviews = stats['total'] or 0
            exp.save(update_fields=['average_rating', 'total_reviews'])
            exp_count += 1

            if stats['total']:
                self.stdout.write(
                    f"  {exp.name}: avg={exp.average_rating} total={exp.total_reviews}"
                )

        self.stdout.write(self.style.SUCCESS(f"  Rebuilt {exp_count} experiences."))

        # ---------- GUIDES ----------
        self.stdout.write(self.style.WARNING("Rebuilding guide ratings..."))

        guide_count = 0
        for guide in GuideProfile.objects.all():
            stats = Review.objects.filter(
                guide=guide,
                review_type='guide',
                moderation_status='approved'
            ).aggregate(avg=Avg('rating'), total=Count('id'))

            guide.average_rating = stats['avg'] or 0
            guide.total_reviews = stats['total'] or 0
            guide.save(update_fields=['average_rating', 'total_reviews'])
            guide_count += 1

            if stats['total']:
                self.stdout.write(
                    f"  {guide.full_name}: avg={guide.average_rating} total={guide.total_reviews}"
                )

        self.stdout.write(self.style.SUCCESS(f"  Rebuilt {guide_count} guides."))
        self.stdout.write(self.style.SUCCESS("Done."))
