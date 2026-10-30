from django import forms
from django.db.models.functions import Lower
from django.forms import ModelForm, modelformset_factory, formset_factory
from .models import PRSeason, Player, PRSeasonResult
from .widgets import BootStrapDateTimePickerInput


class TournamentForm(forms.Form):
    tournament_url = forms.CharField(required=True)
    is_pr_eligible = forms.BooleanField(required=False, initial=True)
    run_in_background = forms.BooleanField(
        required=False, 
        initial=False, 
        label="Large Tournament (Run in background)",
        help_text="Check this for huge tournaments (like the Arcadian) to prevent server timeouts."
    )


class DuplicatePlayer(forms.Form):
    player1 = forms.CharField(required=True, label='Main Player ID')
    player2 = forms.CharField(required=True, label='Duplicate Player ID')


class ConfirmMergeForm(forms.Form):
    confirm_merge = forms.BooleanField(required=True, initial=False, help_text="Check to confirm merging accounts.")



#New PR season editor below this line

MAX_GRAPHIC_BYTES = 10 * 1024 * 1024
ALLOWED_GRAPHIC_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


class PRSeasonForm(forms.ModelForm):
    class Meta:
        model = PRSeason
        fields = ['name', 'start_date', 'end_date', 'is_active', 'region_code', 'graphic']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'region_code': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'graphic': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
        help_texts = {'graphic': 'Optional season graphic (JPG, PNG, WebP or GIF, up to 10 MB). Any size or shape works.'}

    def clean_graphic(self):
        graphic = self.cleaned_data.get('graphic')
        # An unchanged existing file comes back as a FieldFile with no .size check needed.
        if graphic and hasattr(graphic, 'content_type'):
            if graphic.size > MAX_GRAPHIC_BYTES:
                raise forms.ValidationError('That image is over 10 MB; please upload a smaller one.')
            if getattr(graphic.image, 'format', None) not in ALLOWED_GRAPHIC_FORMATS:
                raise forms.ValidationError('Please upload a JPG, PNG, WebP or GIF image.')
        return graphic

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
            # Rank is usually a number but may be a text tier (e.g. IM, HM),
            # so it must be a free text field, capped to the model's max_length.
            'rank': forms.TextInput(attrs={
                'class': 'form-control', 'maxlength': '3',
                'placeholder': '1 or IM / HM',
            }),
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