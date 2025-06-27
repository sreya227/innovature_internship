import random
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from .forms import CustomUserCreationForm
from django.http import HttpResponse,HttpResponseForbidden
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from .models import Group, GroupMembers, Split, Payer, Settlement
from django.db.models.functions import Coalesce
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.contrib import messages
from decimal import Decimal, InvalidOperation
from django.views.decorators.http import require_POST
from django.db.models import Sum, Count, Q, F, OuterRef, Subquery, Exists
from django.views.decorators.cache import never_cache
from datetime import timedelta, datetime
from django.utils.timezone import now
from django.utils.dateparse import parse_datetime
from collections import defaultdict
from django.core.paginator import Paginator
from core.utils import get_category_from_description

def home_view(request):
    if request.user.is_authenticated:
        return redirect('groups')  # or your homepage URL name

    return render(request, 'home.html')

@never_cache
def verify_otp_view(request):
    if 'user_data' not in request.session or 'signup_otp' not in request.session:
        return redirect('signup')

    otp_time_str = request.session.get('signup_otp_time')
    if otp_time_str:
        otp_time = parse_datetime(otp_time_str)
        if otp_time and now() - otp_time > timedelta(minutes=2):
            # Clear session and redirect to signup
            request.session.pop('signup_otp', None)
            request.session.pop('signup_otp_time', None)
            request.session.pop('user_data', None)
            return redirect('signup')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        session_otp = request.session.get('signup_otp')
        user_data = request.session.get('user_data')

        if not session_otp or not user_data:
            return redirect('signup')

        if entered_otp == session_otp:
            user = User.objects.create_user(
                username=user_data['username'],
                email=user_data['email'],
                password=user_data['password1']
            )

            login(request, user)

            request.session.pop('signup_otp', None)
            request.session.pop('signup_otp_time', None)
            request.session.pop('user_data', None)

            return redirect('groups')

        return render(request, 'verify_otp.html', {'error': 'Invalid OTP. Please try again.'})

    return render(request, 'verify_otp.html')
    

def login_view(request):
    error = None
    if request.user.is_authenticated:
        return redirect('groups')  # or your homepage URL name

    if request.method == 'POST':
        identifier = request.POST.get('identifier')  # Can be email or username
        password = request.POST.get('password')

        user = None

        # Check if input is email
        if '@' in identifier:
            try:
                user_obj = User.objects.get(email=identifier)
                username = user_obj.username
            except User.DoesNotExist:
                error = "Email is not registered"
                return render(request, 'login.html', {'error': error})
        else:
            username = identifier

        # Authenticate
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('groups')
        else:
            error = "Oops! Incorrect credentials entered"

    return render(request, 'login.html', {'error': error})

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('groups')  # or your homepage URL name

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user_obj = form.save(commit=False)
            otp = str(random.randint(100000, 999999))

            request.session['user_data'] = {
                'username': user_obj.username,
                'email': user_obj.email,
                'password1': request.POST['password1'],  
            }
            request.session['signup_otp'] = otp
            request.session['signup_otp_time'] = str(now())
            # Send OTP via email
            send_mail(
                'Your Divido OTP Code',
                f'Your OTP is: {otp}',
                settings.DEFAULT_FROM_EMAIL,
                [user_obj.email],
                fail_silently=False,
            )

            return redirect('verify_otp')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'signup.html', {'form': form})
@never_cache
@login_required
def groups_view(request):
    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', '')
    filter_option = request.GET.get('filter', '')
    user = request.user

    # Step 1: Base queryset – groups where user is a member
    groups_queryset = Group.objects.filter(groupmembers__member_id=user).distinct()

    # Step 2: Search by title/description
    if query:
        groups_queryset = groups_queryset.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )

    # Step 3: Apply filter
    if filter_option == "pending_from_others":
        # Groups where someone else still owes money to me
        groups_queryset = groups_queryset.filter(
            split__split_by=user,
            split__payer__paid=False
        ).distinct()

    elif filter_option == "pending_from_me":
        # Groups where I still owe money
        groups_queryset = groups_queryset.filter(
            split__payer__payer_id=user,
            split__payer__paid=False
        ).distinct()

    elif filter_option == "created_by_me":
        groups_queryset = groups_queryset.filter(admin=user)

    elif filter_option == "fully_settled":
        # Groups where all splits are fully paid and all payers are paid
        groups_queryset = groups_queryset.exclude(
            Q(split__fully_paid=False) |
            Q(split__payer__paid=False)
        ).distinct()

    # Step 4: Apply sort
    if sort == "a_to_z":
        groups_queryset = groups_queryset.order_by('title')
    elif sort == "z_to_a":
        groups_queryset = groups_queryset.order_by('-title')
    elif sort == "newest":
        groups_queryset = groups_queryset.order_by('-created_at')
    elif sort == "oldest":
        groups_queryset = groups_queryset.order_by('created_at')

    # Step 5: Pagination (after all filtering/sorting)
    paginator = Paginator(groups_queryset, 3)
    page_number = request.GET.get('page')
    groups = paginator.get_page(page_number)

    # Step 6: Deleted group message
    deleted_title = request.session.pop('deleted_group_title', None)
    if deleted_title:
        messages.error(request, f"Group '{deleted_title}' has been deleted by the admin.")

    # Prepare base querystring without 'page' for pagination links
    querydict = request.GET.copy()
    querydict.pop('page', None)
    preserved_query = querydict.urlencode()
    if preserved_query:
        preserved_query += '&'  # add trailing & for correct URL concatenation

    # Step 7: Render
    return render(request, 'groups.html', {
        'groups': groups,
        'query': query,
        'preserved_query': preserved_query,
    })


@login_required
@never_cache
def create_group_view(request):
    error = None
    error_title = None
    error_members = None

    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description', "")
        member_ids = request.POST.getlist('members')  # List of user IDs

        # Validate required fields
        if not title:
            error_title = "Group title is required."

        if not member_ids:
            error_members = "Select at least one member to add."

        if not error_title and not error_members:
            try:
                group = Group.objects.create(title=title, description=description, admin=request.user)

                # Add current user
                GroupMembers.objects.create(grp_id=group, member_id=request.user)

                # Add selected members
                for member_id in member_ids:
                    user = User.objects.get(id=member_id)
                    if user != request.user:
                        GroupMembers.objects.get_or_create(grp_id=group, member_id=user)

                return redirect('groups')

            except IntegrityError:
                error = "A group with this name already exists. Please choose a different name."

    users = User.objects.exclude(id=request.user.id)
    return render(request, 'create_group.html', {
        'error': error,
        'error_title': error_title,
        'error_members': error_members,
        'users': users
    })

@login_required
@never_cache
def group_detail_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if not GroupMembers.objects.filter(grp_id=group, member_id=request.user).exists():
        return HttpResponseForbidden("You are not a member of this group.")

    # Get sorting and filtering params
    sort_option = request.GET.get('sort', '-created_at')
    filter_type = request.GET.get('filter_type')
    filter_value = request.GET.get('filter_value')
    min_amount = request.GET.get('min_amount')
    max_amount = request.GET.get('max_amount')

    # Base queryset
    splits = Split.objects.filter(grp_id=group)

    # Apply filter
    if filter_type == 'category' and filter_value:
        splits = splits.filter(category=filter_value)
    elif filter_type == 'split_by' and filter_value:
        splits = splits.filter(split_by__username=filter_value)
    elif filter_type == 'payer' and filter_value:
        splits = splits.filter(payer__payer_id__username=filter_value).distinct()
    elif filter_type == 'amount_range':
        if min_amount:
            splits = splits.filter(amount__gte=min_amount)
        if max_amount:
            splits = splits.filter(amount__lte=max_amount)

    # Apply sort
    splits = splits.order_by(sort_option)

    # Mark splits as closed if all dues paid
    for split in splits:
        unpaid_count = split.payer_set.filter(paid=False).exclude(payer_id=split.split_by).count()
        split.is_closed = (unpaid_count == 0)

    # Apply payment status filter
    if filter_type == 'payment_status' and filter_value:
        if filter_value == 'pending':
            splits = [s for s in splits if not s.is_closed]
        elif filter_value == 'paid':
            splits = [s for s in splits if s.is_closed]

    # ✅ NEW: Calculate dues using Settlement
    to_be_paid_total = Decimal('0.00')
    to_pay_total = Decimal('0.00')

    group_members = User.objects.filter(
        id__in=GroupMembers.objects.filter(grp_id=group)
        .exclude(member_id=request.user)
        .values_list('member_id', flat=True)
    )

    for member in group_members:
        # MEMBER owes ME
        owes_me_qs = Payer.objects.filter(
            split_id__grp_id=group,
            split_id__split_by=request.user,
            payer_id=member
        ).annotate(
            paid_amount=Coalesce(Sum('settlement__amount_paid'), Decimal('0.00'))
        ).annotate(
            remaining=F('amount') - F('paid_amount')
        )

        member_owes_me = owes_me_qs.aggregate(
            total=Coalesce(Sum('remaining'), Decimal('0.00'))
        )['total']

        # I owe MEMBER
        i_owe_qs = Payer.objects.filter(
            split_id__grp_id=group,
            split_id__split_by=member,
            payer_id=request.user
        ).annotate(
            paid_amount=Coalesce(Sum('settlement__amount_paid'), Decimal('0.00'))
        ).annotate(
            remaining=F('amount') - F('paid_amount')
        )

        i_owe_member = i_owe_qs.aggregate(
            total=Coalesce(Sum('remaining'), Decimal('0.00'))
        )['total']

        net = member_owes_me - i_owe_member
        if net > 0:
            to_be_paid_total += net
        elif net < 0:
            to_pay_total += abs(net)

    # ✅ Final return after loop
    return render(request, 'group_detail.html', {
        'group': group,
        'splits': splits,
        'to_be_paid': round(to_be_paid_total, 2),
        'to_pay': round(to_pay_total, 2),
        'categories': ['Food', 'Travel', 'Rent', 'Bills', 'Groceries', 'Shopping', 'Entertainment', 'Health', 'Gifts', 'General'],
        'min_amount': min_amount,
        'max_amount': max_amount,
        'filter_type': filter_type,
        'filter_value': filter_value,
    })

@login_required
@never_cache
def create_split_view(request, group_id):
    if request.method == 'POST':
        group = get_object_or_404(Group, pk=group_id)
        user = request.user

        if not GroupMembers.objects.filter(grp_id=group, member_id=user).exists():
            return redirect('group_detail', group_id=group_id)

        amount = Decimal(request.POST.get('amount'))
        description = request.POST.get('description', '')
        split_type = request.POST.get('split_type', 'equal')
        category = get_category_from_description(description)

        split = Split.objects.create(
            grp_id=group,
            split_by=user,
            amount=amount,
            description=description,
            category=category
        )

        members = GroupMembers.objects.filter(grp_id=group)

        if split_type == 'equal':
            share = round(amount / members.count(), 2)
            for member in members:
                Payer.objects.create(
                    split_id=split,
                    payer_id=member.member_id,
                    amount=share,
                    paid=(member.member_id == user)
                )

        elif split_type == 'custom':
            total_custom = Decimal('0.00')
            for member in members:
                key = f"custom_{member.member_id.id}"
                val = request.POST.get(key)
                if val is None:
                    val_decimal = Decimal('0.00')
                else:
                    val_decimal = Decimal(val or '0.00')
                total_custom += val_decimal

                Payer.objects.create(
                    split_id=split,
                    payer_id=member.member_id,
                    amount=val_decimal,
                    paid=(member.member_id == user)
                )

            # Optional: Check if custom total matches
            if abs(total_custom - amount) > Decimal("0.01"):
                messages.error(request, "Custom amounts do not total to full amount.")
                split.delete()
                return redirect('group_detail', group_id=group_id)

        return redirect('group_detail', group_id=group_id)
    
@login_required
@never_cache
def split_detail_view(request, split_id):
    split = get_object_or_404(Split, id=split_id)

    payers = Payer.objects.filter(split_id=split).exclude(payer_id=split.split_by)

    enriched_payers = []
    for payer in payers:
        total_paid = Settlement.objects.filter(payer=payer).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        remaining = payer.amount - total_paid
        enriched_payers.append({
            'obj': payer,
            'total_paid': total_paid,
            'remaining': remaining,
        })

    return render(request, 'split_detail.html', {
        'split': split,
        'payers': enriched_payers
    })

@require_POST
@login_required
def record_settlement_view(request, split_id):
    if request.user.is_anonymous:
        return HttpResponseForbidden("Login required")

    payer_id = request.POST.get('payer_id')
    amount_paid = request.POST.get('amount_paid')

    try:
        amount_paid = round(Decimal(amount_paid), 2)
        if amount_paid <= 0:
            messages.error(request, "Invalid amount.")
            return redirect('split_detail', split_id=split_id)
    except:
        messages.error(request, "Invalid amount format.")
        return redirect('split_detail', split_id=split_id)

    payer = get_object_or_404(Payer, split_id__id=split_id, payer_id__id=payer_id)
    split = payer.split_id

    # Only split creator can record
    if request.user != split.split_by:
        return HttpResponseForbidden("Only the split creator can record payments.")

    # Don't allow overpayment
    total_paid = Settlement.objects.filter(payer=payer).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    remaining = payer.amount - total_paid

    if amount_paid > remaining:
        messages.error(request, f"Cannot pay more than remaining amount (₹{remaining}).")
        return redirect('split_detail', split_id=split_id)

    # Save the payment
    Settlement.objects.create(payer=payer, amount_paid=amount_paid)

    # Mark as paid if fully settled
    if amount_paid == remaining:
        payer.paid = True
        payer.save()

    return redirect('split_detail', split_id=split_id)

@login_required
@never_cache
def dashboard_view(request):
    user = request.user

    # Get all members the user has interacted with financially across all groups
    member_ids = GroupMembers.objects.filter(
        grp_id__in=GroupMembers.objects.filter(member_id=user).values_list('grp_id', flat=True)
    ).exclude(member_id=user).values_list('member_id', flat=True).distinct()

    to_be_paid_total = 0
    to_pay_total = 0

    for member_id in member_ids:
        owes_you = Payer.objects.filter(
            split_id__split_by=user,
            payer_id=member_id,
            paid=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        you_owe = Payer.objects.filter(
            split_id__split_by=member_id,
            payer_id=user,
            paid=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        net = owes_you - you_owe
        if net > 0:
            to_be_paid_total += net
        elif net < 0:
            to_pay_total += abs(net)

    # ✅ NEW LOGIC – add below your totals
    insights = []
    today = now().date()

    # 🎈 Group anniversary today
    group_anniversary = Group.objects.filter(
        groupmembers__member_id=user,
        created_at__day=today.day,
        created_at__month=today.month
    ).first()
    if group_anniversary:
        age_days = (today - group_anniversary.created_at.date()).days
        if age_days >= 365:
            years = age_days // 365
            insights.append(f"🎉 You joined '{group_anniversary.title}' {years} year(s) ago today!")
        else:
            insights.append(f"🎈 You joined '{group_anniversary.title}' {age_days} days ago today!")

    # 📆 First ever split
    first_split = Split.objects.filter(split_by=user).order_by('created_at').first()
    if first_split:
        days_ago = (today - first_split.created_at.date()).days
        if days_ago > 0:
            insights.append(f"📆 Your first recorded split was {days_ago} days ago in '{first_split.grp_id.title}'.")

    # 🏅 Longest group membership
    oldest_group = Group.objects.filter(
        groupmembers__member_id=user
    ).order_by('created_at').first()
    if oldest_group:
        days = (today - oldest_group.created_at.date()).days
        insights.append(f"🏅 You’ve been in '{oldest_group.title}' for {days} days — your longest group!")

    # 👤 Most split with
    top_split_user = Payer.objects.filter(payer_id=user).values(
        user_id=F('split_id__split_by')
    ).annotate(count=Count('id')).order_by('-count').first()
    if top_split_user:
        top_user_obj = User.objects.get(id=top_split_user['user_id'])
        count = top_split_user['count']
        insights.append(f"👤 You've split with {top_user_obj.username} the most — {count} times!")

    # ⌛ Oldest unpaid expense
    oldest_unpaid = Payer.objects.filter(
        payer_id=user,
        paid=False
    ).order_by('split_id__created_at').first()
    if oldest_unpaid:
        days = (today - oldest_unpaid.split_id.created_at.date()).days
        if days > 0:
            insights.append(f"⌛ You’ve had an unpaid expense pending for {days} days.")

    daily_insights = random.sample(insights, min(2, len(insights))) if insights else []

    # 📊 Category-wise overall expenses
    category_summary = Payer.objects.filter(
        payer_id=user,
        paid=True,
        split_id__split_by=user
    ).values('split_id__category').annotate(
        total=Sum('amount')
    ).filter(total__gt=0).order_by('-total')

    category_labels = [entry['split_id__category'] for entry in category_summary]
    category_data = [float(entry['total']) for entry in category_summary]

    top_category = None
    if category_summary:
        top_category = {
            'name': category_summary[0]['split_id__category'],
            'amount': float(category_summary[0]['total'])
        }

    # 🧾 Most Active Group (by split count this month)
    start_of_month = now().replace(day=1)
    active_group = Split.objects.filter(
        grp_id__groupmembers__member_id=user,
        created_at__gte=start_of_month
    ).values('grp_id', 'grp_id__title').annotate(
        count=Count('id')
    ).order_by('-count').first()

    most_active_group = active_group['grp_id__title'] if active_group else None

    # 💰 Top Spending Group (user's own splits this month)
    spending_group = Split.objects.filter(
        split_by=user,
        created_at__gte=start_of_month
    ).values('grp_id', 'grp_id__title').annotate(
        total=Sum('amount')
    ).order_by('-total').first()

    top_spending_group = {
        'name': spending_group['grp_id__title'],
        'amount': float(spending_group['total'])
    } if spending_group else None

    # 👥 Frequent Split With
    as_payer = Payer.objects.filter(
        payer_id=user,
        split_id__created_at__gte=start_of_month
    ).exclude(split_id__split_by=user).values(
        user_id=F('split_id__split_by')
    ).annotate(count=Count('id'))

    as_split_by = Payer.objects.filter(
        split_id__split_by=user,
        split_id__created_at__gte=start_of_month
    ).exclude(payer_id=user).values(
        user_id=F('payer_id')
    ).annotate(count=Count('id'))

    interaction_counter = defaultdict(int)
    for entry in list(as_payer) + list(as_split_by):
        interaction_counter[entry['user_id']] += entry['count']

    frequent_user_id = max(interaction_counter, key=interaction_counter.get, default=None)
    frequent_split_with = None
    if frequent_user_id:
        frequent_user = User.objects.get(id=frequent_user_id)
        frequent_split_with = {
            'name': frequent_user.username,
            'count': interaction_counter[frequent_user_id]
        }

    # 📈 Average Daily Spend This Month
    days_passed = (now().date() - start_of_month.date()).days + 1
    total_paid = Split.objects.filter(
        split_by=user,
        created_at__gte=start_of_month
    ).aggregate(total=Sum('amount'))['total'] or 0

    average_daily_spend = round(float(total_paid) / days_passed, 2)

            # ✅ Total Transactions: Count of paid settlements involving the user (excluding self-pays)
    paid_settlements = Settlement.objects.filter(
        Q(payer__payer_id=user) | Q(payer__split_id__split_by=user)
    ).exclude(
        payer__payer_id=user,
        payer__split_id__split_by=user
    )

    total_transactions = paid_settlements.count()

    context = {
        'user': user,
        'to_be_paid': round(to_be_paid_total, 2),
        'to_pay': round(to_pay_total, 2),
        'daily_insights': daily_insights,
        'category_labels': category_labels,
        'category_data': category_data,
        'top_category': top_category,
        'most_active_group': most_active_group,
        'top_spending_group': top_spending_group,
        'frequent_split_with': frequent_split_with,
        'average_daily_spend': average_daily_spend,
        'total_transactions': total_transactions,
    }

    return render(request, 'dashboard.html', context)


@login_required
@never_cache
def transactions_view(request):
    user = request.user

    settlements = Settlement.objects.filter(
        Q(payer__payer_id=user) | Q(payer__split_id__split_by=user)
    ).exclude(
        payer__payer_id=F('payer__split_id__split_by')  # Skip self-pay
    ).select_related(
        'payer',
        'payer__split_id',
        'payer__split_id__grp_id',
        'payer__split_id__split_by',
        'payer__payer_id'
    ).order_by('-paid_on')

    return render(request, 'transactions.html', {
        'transactions': settlements,
        'user': user,
    })

@login_required
def leave_group_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    user = request.user

    # Check if the user owes money (has unpaid "to pay")
    unpaid_to_pay = Payer.objects.filter(
        split_id__grp_id=group,
        payer_id=user,
        paid=False
    ).exists()

    # Check if others owe the user money (has unpaid "to be paid")
    unpaid_to_be_paid = Payer.objects.filter(
        split_id__grp_id=group,
        split_id__split_by=user,
        paid=False
    ).exclude(payer_id=user).exists()

    if unpaid_to_pay or unpaid_to_be_paid:
        messages.error(request, "You cannot leave the group until all your pending dues are settled.")
        return redirect('group_detail', group_id=group.id)

    # Remove user from the group
    GroupMembers.objects.filter(grp_id=group, member_id=user).delete()
    messages.success(request, "You have successfully left the group.")
    return redirect('groups')
    
@login_required
@never_cache
def group_info_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    # Check if current user is a member
    if not GroupMembers.objects.filter(grp_id=group, member_id=request.user).exists():
        return HttpResponseForbidden("You are not a member of this group.")

    is_admin = group.admin == request.user

    # Get all group members (User instances)
    members = User.objects.filter(
        id__in=GroupMembers.objects.filter(grp_id=group).values_list('member_id', flat=True)
    )

    # Users not in group
    users_not_in_group = User.objects.exclude(id__in=members.values_list('id', flat=True))

    # Find removable members (no unpaid dues)
    removable_members = []
    for member in members:
        owes = Payer.objects.filter(split_id__grp_id=group, payer_id=member, paid=False).exists()
        is_owed = Payer.objects.filter(
            split_id__grp_id=group, split_id__split_by=member, paid=False
        ).exclude(payer_id=member).exists()
        if not owes and not is_owed:
            removable_members.append(member)
            # Check if all other members have received all their dues
    can_delete_group = True
    for member in members.exclude(id=group.admin.id):
        to_be_paid = Payer.objects.filter(
            split_id__grp_id=group,
            split_id__split_by=member,
            paid=False
        ).exclude(payer_id=member).exists()
        if to_be_paid:
            can_delete_group = False
            break
    context = {
        'group': group,
        'members': members,
        'is_admin': is_admin,
        'users_not_in_group': users_not_in_group,
        'removable_members': removable_members,
        'can_delete_group': can_delete_group,
    }

    return render(request, 'group_info.html', context)
    
@require_POST
@login_required
def add_member_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if request.user != group.admin:
        return HttpResponseForbidden("Only admin can add members.")

    user_id = request.POST.get('user_to_add')
    user = get_object_or_404(User, id=user_id)

    if not GroupMembers.objects.filter(grp_id=group, member_id=user).exists():
        GroupMembers.objects.create(grp_id=group, member_id=user)
        messages.success(request, f"{user.username} added to the group.")
    else:
        messages.warning(request, "User is already a member.")

    return redirect('group_info', group_id=group_id)


@require_POST
@login_required
def remove_member_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if request.user != group.admin:
        return HttpResponseForbidden("Only admin can remove members.")

    user_id = request.POST.get('user_to_remove')
    user = get_object_or_404(User, id=user_id)

    # Check dues
    owes = Payer.objects.filter(split_id__grp_id=group, payer_id=user, paid=False).exists()
    is_owed = Payer.objects.filter(split_id__grp_id=group, split_id__split_by=user, paid=False).exclude(payer_id=user).exists()

    if owes or is_owed:
        messages.error(request, f"{user.username} cannot be removed due to pending dues.")
    else:
        GroupMembers.objects.filter(grp_id=group, member_id=user).delete()
        messages.success(request, f"{user.username} removed from the group.")

    return redirect('group_info', group_id=group_id)

@login_required
@never_cache
def dues_view(request, group_id=None):
    user = request.user
    dues_summary = []
    dues_type = request.GET.get('type', 'to-be-paid')

    if group_id:
        group = get_object_or_404(Group, id=group_id)
        members = User.objects.filter(
            id__in=GroupMembers.objects.filter(grp_id=group).values_list('member_id', flat=True)
        ).exclude(id=user.id)
    else:
        group = None
        members = User.objects.exclude(id=user.id)

    for member in members:
        if group_id:
            you_owe_qs = Payer.objects.filter(
                split_id__grp_id=group,
                payer_id=user,
                split_id__split_by=member
            ).select_related('split_id')

            they_owe_qs = Payer.objects.filter(
                split_id__grp_id=group,
                payer_id=member,
                split_id__split_by=user
            ).select_related('split_id')
        else:
            you_owe_qs = Payer.objects.filter(
                payer_id=user,
                split_id__split_by=member
            ).select_related('split_id', 'split_id__grp_id')

            they_owe_qs = Payer.objects.filter(
                payer_id=member,
                split_id__split_by=user
            ).select_related('split_id', 'split_id__grp_id')

        you_owe = 0
        they_owe = 0
        you_owe_splits = []
        they_owe_splits = []

        for p in you_owe_qs:
            total_paid = Settlement.objects.filter(payer=p).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
            remaining = p.amount - total_paid
            if remaining > 0:
                you_owe += remaining
                you_owe_splits.append({
                    'split': p.split_id,
                    'amount': p.amount,
                    'paid': total_paid,
                    'remaining': remaining,
                })

        for p in they_owe_qs:
            total_paid = Settlement.objects.filter(payer=p).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
            remaining = p.amount - total_paid
            if remaining > 0:
                they_owe += remaining
                they_owe_splits.append({
                    'split': p.split_id,
                    'amount': p.amount,
                    'paid': total_paid,
                    'remaining': remaining,
                })

        if dues_type == 'to-be-paid' and they_owe > you_owe:
            net = round(they_owe - you_owe, 2)
            dues_summary.append({
                'user': member,
                'amount': net,
                'is_positive': True,
                'splits': they_owe_splits
            })

        elif dues_type == 'to-pay' and you_owe > they_owe:
            net = round(you_owe - they_owe, 2)
            dues_summary.append({
                'user': member,
                'amount': net,
                'is_positive': False,
                'splits': you_owe_splits
            })

    return render(request, 'dues_list.html', {
        'dues': dues_summary,
        'label': "Your Dues in This Group" if group_id else "Your Dues Across All Groups",
        'group': group,
        'dues_type': dues_type,
    })
    
@require_POST
@login_required
def delete_group_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if request.user != group.admin:
        return HttpResponseForbidden("Only the admin can delete this group.")

    # Get all members excluding admin
    members = GroupMembers.objects.filter(grp_id=group).exclude(member_id=request.user)

    # Check if any of these members are still owed dues
    for gm in members:
        is_owed = Payer.objects.filter(
            split_id__grp_id=group,
            split_id__split_by=gm.member_id,
            paid=False
        ).exclude(payer_id=gm.member_id).exists()
        
        if is_owed:
            messages.error(request, "Group cannot be deleted. Some members are still owed dues.")
            return redirect('group_info', group_id=group.id)

    # Save the group title to show a message after redirect
    request.session['deleted_group_title'] = group.title

    # Delete the group and its dependencies (GroupMembers, Splits, etc.)
    group.delete()

    return redirect('groups')
    
@never_cache
def forgot_password_request_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return render(request, 'forgot_password.html', {
                'error': 'No user found with this email.'
            })

        otp = str(random.randint(100000, 999999))
        request.session['reset_email'] = email
        request.session['reset_otp'] = otp
        request.session['reset_otp_time'] = str(now())

        print(f"[DEBUG] OTP for password reset: {otp}")  # safe for now

        # Optional: send OTP via email
        # send_mail(
        #     'Your Password Reset OTP',
        #     f'Your OTP is: {otp}',
        #     settings.DEFAULT_FROM_EMAIL,
        #     [email],
        #     fail_silently=False,
        # )

        return redirect('verify_reset_otp')

    return render(request, 'forgot_password.html')

@never_cache
def verify_reset_otp_view(request):
    if 'reset_email' not in request.session or 'reset_otp' not in request.session:
        return redirect('forgot_password')  # fallback if session expired or invalid

    otp_time_str = request.session.get('reset_otp_time')
    if otp_time_str:
        otp_time = parse_datetime(otp_time_str)
        if otp_time and now() - otp_time > timedelta(minutes=2):
            request.session.pop('reset_email', None)
            request.session.pop('reset_otp', None)
            request.session.pop('reset_otp_time', None)
            return redirect('forgot_password')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        session_otp = request.session.get('reset_otp')

        if entered_otp == session_otp:
            # Allow them to set a new password
            return redirect('reset_password')  # show password reset form

        return render(request, 'verify_otp.html', {'error': 'Invalid OTP. Please try again.'})

    return render(request, 'verify_otp.html')
@never_cache
def reset_password_view(request):
    if 'reset_email' not in request.session:
        return redirect('login')

    if request.method == 'POST':
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if not password1 or not password2:
            return render(request, 'reset_password.html', {'error': 'Both fields are required.'})
        if password1 != password2:
            return render(request, 'reset_password.html', {'error': 'Passwords do not match.'})
        if len(password1) < 6:
            return render(request, 'reset_password.html', {'error': 'Password must be at least 6 characters long.'})

        try:
            user = User.objects.get(email=request.session['reset_email'])
            user.set_password(password1)
            user.save()
            # Clear session
            request.session.pop('reset_email', None)
            return redirect('login')
        except User.DoesNotExist:
            return redirect('login')

    return render(request, 'reset_password.html')




