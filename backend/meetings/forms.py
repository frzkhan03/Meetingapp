from django import forms
from .models import Meeting


class MeetingForm(forms.ModelForm):
    start_date = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'form-control'
            }
        )
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(
            attrs={
                'type': 'time',
                'class': 'form-control'
            }
        )
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(
            attrs={
                'type': 'time',
                'class': 'form-control'
            }
        )
    )

    class Meta:
        model = Meeting
        fields = ['name', 'description', 'location', 'is_all_day', 'recurrence', 'require_approval']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Add a title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Add details about the meeting...'
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Add a location (optional)'
            }),
            'is_all_day': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'recurrence': forms.Select(attrs={
                'class': 'form-select'
            }),
            'require_approval': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Title'
        self.fields['description'].label = 'Description'
        self.fields['description'].required = False
        self.fields['location'].required = False
        self.fields['recurrence'].label = 'Repeat'

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        is_all_day = cleaned_data.get('is_all_day')

        if not is_all_day and start_time and end_time and end_time <= start_time:
            raise forms.ValidationError('End time must be after start time.')

        return cleaned_data
