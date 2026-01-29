from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import Organization
from meet.validators import (
    validate_username,
    validate_email,
    validate_password_strength,
    validate_organization_name,
    sanitize_input
)


class RegisterForm(UserCreationForm):
    """
    Secure registration form with enhanced validation.
    """
    email = forms.EmailField(required=True)
    organization_name = forms.CharField(
        max_length=255,
        required=False,
        help_text='Create a new organization or leave blank for a personal workspace'
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

        # Add security hints
        self.fields['password1'].help_text = (
            'Password must be at least 10 characters with uppercase, '
            'lowercase, number, and special character.'
        )

    def clean_username(self):
        """Validate and sanitize username"""
        username = self.cleaned_data.get('username')
        username = sanitize_input(username, max_length=30)

        try:
            validate_username(username)
        except ValidationError as e:
            raise ValidationError(e.message)

        # Check if username already exists (case-insensitive)
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already taken')

        return username

    def clean_email(self):
        """Validate and sanitize email"""
        email = self.cleaned_data.get('email')

        try:
            email = validate_email(email)
        except ValidationError as e:
            raise ValidationError(e.message)

        # Check if email already exists
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists')

        return email

    def clean_password1(self):
        """Enhanced password validation"""
        password = self.cleaned_data.get('password1')

        try:
            validate_password_strength(password)
        except ValidationError as e:
            raise ValidationError(e.messages if hasattr(e, 'messages') else e.message)

        return password

    def clean_organization_name(self):
        """Sanitize organization name"""
        name = self.cleaned_data.get('organization_name')
        if name:
            try:
                name = validate_organization_name(name)
            except ValidationError as e:
                raise ValidationError(e.message)
        return name


class LoginForm(AuthenticationForm):
    """
    Secure login form with input sanitization.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_username(self):
        """Sanitize username input"""
        username = self.cleaned_data.get('username')
        return sanitize_input(username, max_length=150)


class OrganizationForm(forms.ModelForm):
    """
    Organization form with input sanitization.
    """

    class Meta:
        model = Organization
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_name(self):
        """Validate and sanitize organization name"""
        name = self.cleaned_data.get('name')

        try:
            name = validate_organization_name(name)
        except ValidationError as e:
            raise ValidationError(e.message)

        return name
