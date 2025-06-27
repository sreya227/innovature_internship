from django.db import models
from django.contrib.auth.models import User

class Group(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class GroupMembers(models.Model):
    grp_id = models.ForeignKey(Group, on_delete=models.CASCADE)
    member_id = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        unique_together = ['grp_id', 'member_id']
        verbose_name = "Group member"
        verbose_name_plural = "Group members"

    def __str__(self):
        return f"{self.member_id.username} in {self.grp_id.title}"

class Split(models.Model):
    grp_id = models.ForeignKey(Group, on_delete=models.CASCADE)
    split_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='splits_paid')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    fully_paid = models.BooleanField(default=False)

    CATEGORY_CHOICES = [
        ('Food', 'Food'),
        ('Travel', 'Travel'),
        ('Rent', 'Rent'),
        ('Bills', 'Bills'),
        ('Groceries', 'Groceries'),
        ('Shopping', 'Shopping'),
        ('Entertainment', 'Entertainment'),
        ('Health', 'Health'),
        ('Gifts', 'Gifts'),
        ('General', 'General'),
    ]

    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='General'
    )

    def __str__(self):
        return f"{self.description} - {self.amount} in {self.grp_id.title}"

class Payer(models.Model):
    split_id = models.ForeignKey(Split, on_delete=models.CASCADE)
    payer_id = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)

    class Meta:
        unique_together = ['split_id', 'payer_id']

    def __str__(self):
        return f"{self.payer_id.username} owes {self.amount} for {self.split_id.description}"

class Settlement(models.Model):
    payer = models.ForeignKey(Payer, on_delete=models.CASCADE)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payer.payer_id.username} paid ₹{self.amount_paid} on {self.paid_on.date()}"


