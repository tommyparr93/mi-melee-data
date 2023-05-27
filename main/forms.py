from django import forms


class TournamentForm(forms.Form):
    tournament_url = forms.CharField(required=True)
    is_pr_eligible = forms.BooleanField(required=False, initial=False)
