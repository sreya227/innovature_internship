from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Group, GroupMembers, Split, Payer, Settlement

admin.site.register(Group)
admin.site.register(GroupMembers)
admin.site.register(Split)
admin.site.register(Payer)
admin.site.register(Settlement)
