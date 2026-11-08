# Django model that represents the database
from django.db import models
from django.core.validators import FileExtensionValidator


class AuthGroup(models.Model):
    name = models.CharField(unique=True, max_length=150)

    class Meta:
        managed = False
        db_table = 'auth_group'


class AuthGroupPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
    permission = models.ForeignKey('AuthPermission', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_group_permissions'
        unique_together = (('group', 'permission'),)


class AuthPermission(models.Model):
    name = models.CharField(max_length=255)
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING)
    codename = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'auth_permission'
        unique_together = (('content_type', 'codename'),)


class AuthUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.BooleanField()
    username = models.CharField(unique=True, max_length=150)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.CharField(max_length=254)
    is_staff = models.BooleanField()
    is_active = models.BooleanField()
    date_joined = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auth_user'


class AuthUserGroups(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_groups'
        unique_together = (('user', 'group'),)


class AuthUserUserPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    permission = models.ForeignKey(AuthPermission, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_user_permissions'
        unique_together = (('user', 'permission'),)


class DjangoAdminLog(models.Model):
    action_time = models.DateTimeField()
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.SmallIntegerField()
    change_message = models.TextField()
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'django_admin_log'


class DjangoContentType(models.Model):
    app_label = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'django_content_type'
        unique_together = (('app_label', 'model'),)


class DjangoMigrations(models.Model):
    id = models.BigAutoField(primary_key=True)
    app = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    applied = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_migrations'


class DjangoSession(models.Model):
    session_key = models.CharField(primary_key=True, max_length=40)
    session_data = models.TextField()
    expire_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_session'


class Character(models.Model):
    name = models.CharField(max_length=50, unique=True)
    icon_path = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'character'


class Player(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    region_code = models.ForeignKey('Region', models.DO_NOTHING, db_column='region_code', blank=True, null=True)
    
    # New Relational Fields
    main_char = models.ForeignKey(Character, on_delete=models.SET_NULL, null=True, blank=True, related_name='main_players')
    secondary_char = models.ForeignKey(Character, on_delete=models.SET_NULL, null=True, blank=True, related_name='secondary_players')
    
    pr_notable = models.BooleanField(blank=True, null=True, default=False)
    pr_eligible = models.BooleanField(blank=True, null=True, default=False)
    main_account = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    startgg_slug = models.CharField(max_length=64, blank=True, null=True)

    def __str__(self):
        return self.name if self.name is not None else "Unknown Player"

    @property
    def startgg_url(self):
        return f'https://www.start.gg/user/{self.startgg_slug}' if self.startgg_slug else None

    class Meta:
        db_table = 'player'


class Region(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(blank=True, null=True)

    def __str__(self):
        return self.name
    class Meta:
        db_table = 'region'


class Set(models.Model):
    id = models.IntegerField(primary_key=True)
    player1 = models.ForeignKey(Player, models.DO_NOTHING, db_column='player1', blank=True, null=True)
    player2 = models.ForeignKey(Player, models.DO_NOTHING, db_column='player2', related_name='sets_player2_set', blank=True, null=True)
    player1_score = models.IntegerField(blank=True, null=True)
    player2_score = models.IntegerField(blank=True, null=True)
    winner_id = models.IntegerField(blank=True, null=True)
    tournament = models.ForeignKey('Tournament', blank=True, null=True, on_delete=models.CASCADE)
    location = models.CharField(blank=True, null=True)
    played = models.BooleanField(blank=True, null=True)
    pr_eligible = models.BooleanField(default=True, null=False)

    def __str__(self):
        return f"{self.player1} vs {self.player2} @ {self.tournament} {self.location}"

    class Meta:
        db_table = 'set'


# Region ids are assigned by hand (Region.id is not an auto-increment column).
MICHIGAN_REGION_CODE = 7
NATIONAL_REGION_CODE = 100


class PRSeason(models.Model):
    name = models.CharField(max_length=255)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False, null=False)
    region_code = models.ForeignKey(Region, models.DO_NOTHING, db_column='region_code', blank=True, null=True,
                                    related_name='seasons')
    # The season's custom PR graphic. Any aspect ratio / format; shown as the page hero when set.
    graphic = models.ImageField(upload_to='season_graphics/', blank=True, null=True)
    # Optional video version of the graphic (some seasons are announced as a video).
    graphic_video = models.FileField(
        upload_to='season_videos/', blank=True, null=True,
        validators=[FileExtensionValidator(['mp4', 'm4v', 'webm'])])

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'pr_season'
        constraints = [
            # Several views pick "the" active season with .filter(is_active=True).first().
            models.CheckConstraint(
                condition=~models.Q(is_active=True, region_code=NATIONAL_REGION_CODE),
                name='pr_season_national_never_active',
                violation_error_message='A National season cannot be the active season.',
            ),
        ]


class PRSeasonResult(models.Model):

    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    pr_season = models.ForeignKey(PRSeason, on_delete=models.CASCADE)
    rank = models.CharField(max_length=3)

    class Meta:
        db_table = 'pr_season_results'
        unique_together = ('player', 'pr_season',)


class RankingListEntry(models.Model):
    """One row of a published ranking list, exactly as the source printed it.

    Every row is kept, including players we can't find in the database (player
    is null). PRSeasonResult only holds the rows that matched a player.
    """
    pr_season = models.ForeignKey(PRSeason, on_delete=models.CASCADE, related_name='ranking_entries')
    player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='ranking_entries')
    source_tag = models.CharField(max_length=255)
    rank = models.CharField(max_length=20)
    previous_rank = models.CharField(max_length=20, blank=True, default='')
    score = models.FloatField(null=True, blank=True)
    # The full source row (wikitext or CSV), so no value on the list is lost.
    raw_row = models.TextField(blank=True, default='')

    def __str__(self):
        return f'{self.rank} {self.source_tag} ({self.pr_season})'

    class Meta:
        db_table = 'ranking_list_entry'
        unique_together = ('pr_season', 'source_tag',)


class Tournament(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(blank=True, null=True)
    date = models.DateField(blank=True, null=True)
    pr_season = models.ForeignKey(PRSeason, on_delete=models.CASCADE, null=True, blank=True)
    region_code = models.ForeignKey(Region, models.DO_NOTHING, db_column='region_code', blank=True, null=True)
    entrant_count = models.IntegerField(blank=True, null=True)
    online = models.BooleanField(blank=True, null=True)
    type = models.CharField(blank=True, null=True)
    city = models.CharField(blank=True, null=True)
    slug = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    lat = models.FloatField(blank=True, null=True)
    lng = models.FloatField(blank=True, null=True)
    venue_name = models.CharField(max_length=255, blank=True, null=True)
    venue_address = models.CharField(max_length=500, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'tournament'

    @property
    def winner(self):
        winner_result = TournamentResults.objects.filter(tournament=self, placement=1).first()
        if winner_result:
            return winner_result.player_id  # assuming player_id is the Player instance you want
        return None

# something really funky is happening here due to django not liking composite keys
# This is because I built the database with composite keys originally,
# don't touch lmao
class TournamentResults(models.Model):
    tournament = models.OneToOneField(Tournament, primary_key=True, on_delete=models.CASCADE)  # The composite primary key (tour_id, playerid) found, that is not supported. The first column is selected.
    player_id = models.ForeignKey(Player, models.DO_NOTHING, db_column='player_id')
    name = models.CharField(blank=True, null=True)
    placement = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tournament_results'
        unique_together = (('tournament', 'player_id'),)


class SyncErrorLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    tournament_name = models.CharField(max_length=255, blank=True, null=True)
    tournament_slug = models.CharField(max_length=255, blank=True, null=True)
    tournament_url = models.URLField(max_length=500, blank=True, null=True)
    error_message = models.TextField()
    is_resolved = models.BooleanField(default=False)

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] Error parsing {self.tournament_name or self.tournament_slug}"

    class Meta:
        db_table = 'sync_error_log'
        ordering = ['-timestamp']


class AgentBudgetDay(models.Model):
    """One row per day: what Ask Tom has spent, and what in-flight calls have on hold."""
    day = models.DateField(primary_key=True)
    spent_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    reserved_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    credit_exhausted = models.BooleanField(default=False)

    class Meta:
        db_table = 'agent_budget_day'


class AgentTurn(models.Model):
    """One question and answer. This is both the audit log and the rate-limit counter."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(max_length=10, default='web')     # web or eval
    conversation_id = models.CharField(max_length=32, blank=True, db_index=True)
    ip_hash = models.CharField(max_length=32, blank=True, db_index=True)
    session_hash = models.CharField(max_length=32, blank=True, db_index=True)
    backend = models.CharField(max_length=10, blank=True)
    model = models.CharField(max_length=60, blank=True)
    question = models.TextField()
    answer = models.TextField(blank=True)
    tools = models.JSONField(default=list, blank=True)
    steps = models.IntegerField(default=0)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cache_read_tokens = models.IntegerField(default=0)
    cache_write_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    outcome = models.CharField(max_length=12, default='started')
    seconds = models.FloatField(default=0)
    reported_at = models.DateTimeField(null=True, blank=True, db_index=True)
    report_note = models.TextField(blank=True)

    class Meta:
        db_table = 'agent_turn'
