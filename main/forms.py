from django import forms
from django.db.models.functions import Lower
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



#New PR season editor below this line

class PRSeasonForm(forms.ModelForm):
    class Meta:
        model = PRSeason
        fields = ['name', 'start_date', 'end_date', 'is_active', 'region_code']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'region_code': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class PRSeasonResultForm(forms.ModelForm):
    # We use a CharField for search, then clean it to find the Player object
    player_name = forms.CharField(
        label="Search Player",
        widget=forms.TextInput(attrs={
            'list': 'player-datalist',
            'class': 'form-control',
            'placeholder': 'Start typing tag...',
            'autocomplete': 'off'
        })
    )

    class Meta:
        model = PRSeasonResult
        fields = ['rank']
        widgets = {
            'rank': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        }

    def clean_player_name(self):
        name = self.cleaned_data.get('player_name')
        # This finds the first player matching the name, regardless of flags
        player = Player.objects.filter(name__iexact=name).first()

        if not player:
            raise forms.ValidationError("Player not found in database.")
        return player

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.player_id = self.cleaned_data['player_name']
        if commit:
            instance.save()
        return instance