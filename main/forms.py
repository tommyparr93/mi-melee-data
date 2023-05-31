from django import forms
from .models import PRSeason
from .widgets import BootStrapDateTimePickerInput


class TournamentForm(forms.Form):
    tournament_url = forms.CharField(required=True)
    is_pr_eligible = forms.BooleanField(required=False, initial=False)


class PRSeasonForm(forms.Form):
    season_name = forms.CharField(required=True)
    is_active = forms.BooleanField(required=False)
    season_start = forms.DateTimeField(
        required=True,
        input_formats=['%d/%m/%Y'],
        widget=BootStrapDateTimePickerInput()
    )
    season_end = forms.DateTimeField(
        required=True,
        input_formats=['%d/%m/%Y'],
        widget=BootStrapDateTimePickerInput()
    )


class PRForm(forms.Form):
    csvfile = forms.FileField(label='CSV File', required=True)
    pr_season = forms.ModelChoiceField(queryset=PRSeason.objects.all())
