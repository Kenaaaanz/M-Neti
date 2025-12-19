from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth import password_validation
from django.utils import timezone
from .models import CustomUser, UserSession, Tenant
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import get_user_model

# Get the custom user model
CustomUser = get_user_model()

class CustomLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': ' ',
            'id': 'login-username'
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': ' ',
            'id': 'login-password'
        })

class RegistrationForm(UserCreationForm):
    ACCOUNT_TYPE_CHOICES = [
        ('prepaid', 'Prepaid'),
        ('postpaid', 'Postpaid'),
        ('corporate', 'Corporate'),
    ]
    
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True, max_length=30)
    last_name = forms.CharField(required=True, max_length=30)
    phone = forms.CharField(required=True, max_length=15)
    account_type = forms.ChoiceField(choices=ACCOUNT_TYPE_CHOICES, required=True)
    company_account_number = forms.CharField(required=False, max_length=20)
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        required=False,
        empty_label="-- Select your ISP --"
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'first_name', 'last_name', 'phone', 
            'account_type', 'company_account_number', 'tenant',
            'password1', 'password2'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set tenant queryset
        self.fields['tenant'].queryset = Tenant.objects.filter(is_active=True)
        
        # Update all field widgets with consistent styling
        for field_name, field in self.fields.items():
            if hasattr(field, 'widget') and hasattr(field.widget, 'attrs'):
                base_classes = "w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition duration-200"
                
                if field_name in ['password1', 'password2']:
                    field.widget.attrs.update({
                        'class': base_classes,
                        'placeholder': f'Enter your {field.label.lower()}'
                    })
                elif isinstance(field, forms.ChoiceField) or isinstance(field, forms.ModelChoiceField):
                    field.widget.attrs.update({'class': base_classes})
                else:
                    field.widget.attrs.update({
                        'class': base_classes,
                        'placeholder': f'Enter your {field.label.lower()}' if field.label else ''
                    })
        
        # Specific placeholders
        self.fields['username'].widget.attrs['placeholder'] = 'Choose a username'
        self.fields['email'].widget.attrs['placeholder'] = 'your@email.com'
        self.fields['phone'].widget.attrs['placeholder'] = '+254 700 000000'
        self.fields['company_account_number'].widget.attrs['placeholder'] = 'Optional - auto-generate if blank'
        self.fields['password1'].widget.attrs['placeholder'] = 'Create a password'
        self.fields['password2'].widget.attrs['placeholder'] = 'Confirm your password'

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("This email address is already registered.")
        return email

    def clean_company_account_number(self):
        account_number = self.cleaned_data.get('company_account_number')
        if account_number and CustomUser.objects.filter(company_account_number=account_number).exists():
            raise forms.ValidationError("This company account number is already registered.")
        return account_number

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.phone = self.cleaned_data['phone']
        user.account_type = self.cleaned_data['account_type']
        user.role = 'customer'  # Set default role
        user.registration_status = 'pending'
        user.registration_status = 'pending'
        
        # Set company account number if provided
        if self.cleaned_data.get('company_account_number'):
            user.company_account_number = self.cleaned_data['company_account_number']
        
        # Assign tenant if selected
        if self.cleaned_data.get('tenant'):
            user.tenant = self.cleaned_data['tenant']
        else:
            # Assign to default tenant if none selected
            default_tenant = Tenant.objects.filter(is_active=True).first()
            if default_tenant:
                user.tenant = default_tenant
        
        if commit:
            user.save()
        return user

class UserUpdateForm(forms.ModelForm):
    current_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter current password to confirm changes'
        }),
        help_text="Required to save changes to sensitive information"
    )
    
    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'email', 'phone', 'address', 
                 'city', 'state', 'country', 'zip_code')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.Select(attrs={'class': 'form-control'}),
            'zip_code': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if self.has_changed() and not self.instance.check_password(current_password):
            raise forms.ValidationError("Current password is incorrect.")
        return current_password

class CustomPasswordChangeForm(forms.Form):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Current password'
        })
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password'
        }),
        validators=[password_validation.validate_password]
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password'
        })
    )
    
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    
    def clean_old_password(self):
        old_password = self.cleaned_data.get('old_password')
        if not self.user.check_password(old_password):
            raise forms.ValidationError("Current password is incorrect.")
        return old_password
    
    def clean_new_password2(self):
        new_password1 = self.cleaned_data.get('new_password1')
        new_password2 = self.cleaned_data.get('new_password2')
        
        if new_password1 and new_password2 and new_password1 != new_password2:
            raise forms.ValidationError("Passwords don't match.")
        
        password_validation.validate_password(new_password2, self.user)
        return new_password2
    
    def save(self):
        self.user.set_password(self.cleaned_data['new_password1'])
        self.user.last_password_change = timezone.now()
        self.user.save()
        return self.user

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            'first_name', 'last_name', 'email', 'phone', 'address',
            'city', 'state', 'country', 'zip_code',
            'email_notifications', 'sms_notifications', 'billing_reminders',
            'service_updates', 'promotional_offers', 'language', 
            'timezone', 'date_format', 'dark_mode'
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'placeholder': '+254...', 'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.Select(attrs={'class': 'form-control'}),
            'zip_code': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

class NotificationPreferencesForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ('email_notifications', 'sms_notifications', 'billing_reminders', 
                 'service_updates', 'promotional_offers')
        widgets = {
            'email_notifications': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'sms_notifications': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'billing_reminders': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'service_updates': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'promotional_offers': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
        }

class AccountPreferencesForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ('language', 'timezone', 'date_format', 'dark_mode')
        widgets = {
            'language': forms.Select(attrs={'class': 'form-control'}),
            'timezone': forms.Select(attrs={'class': 'form-control'}),
            'date_format': forms.Select(attrs={'class': 'form-control'}),
            'dark_mode': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
        }

class BillingAddressForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ('address', 'city', 'state', 'country', 'zip_code')
        widgets = {
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.Select(attrs={'class': 'form-control'}),
            'zip_code': forms.TextInput(attrs={'class': 'form-control'}),
        }