from django import forms
from django.forms import ModelForm, modelformset_factory, formset_factory
from .models import PRSeason, Player, PRSeasonResult
from .widgets import BootStrapDateTimePickerInput


class TournamentForm(forms.Form):
    tournament_url = forms.CharField(required=True)
    is_pr_eligible = forms.BooleanField(required=False, initial=True)


class DuplicatePlayer(forms.Form):
    player1 = forms.CharField(required=True, label='Main Player ID')
    player2 = forms.CharField(required=True, label='Duplicate Player ID')


class ConfirmMergeForm(forms.Form):
    confirm_merge = forms.BooleanField(required=True, initial=False, help_text="Check to confirm merging accounts.")


class PRSeasonForm1(forms.Form):
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


class PRSeasonForm(forms.Form):
    pr_season = forms.ModelChoiceField(queryset=PRSeason.objects.all())


PRSeasonResultFormSet = modelformset_factory(
    PRSeasonResult,
    fields=('player', 'rank'),
    extra=1
)

# Create the form and formset instances
pr_season_form = PRSeasonForm()
pr_season_result_formset = PRSeasonResultFormSet(queryset=PRSeasonResult.objects.none())

# Set the region filter for the player field in the formset
pr_season_result_formset.form.base_fields['player'].queryset = Player.objects.filter(region_code=7)

