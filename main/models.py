# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


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


class Player(models.Model):
    playerid = models.AutoField(primary_key=True)
    name = models.CharField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    region_code = models.ForeignKey('Region', models.DO_NOTHING, db_column='region_code', blank=True, null=True)
    character_main = models.CharField(blank=True, null=True)
    character_alt = models.CharField(blank=True, null=True)
    pr_rank = models.IntegerField(db_column='PR_rank', blank=True, null=True)  # Field name made lowercase.

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = 'player'


class Region(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = 'region'


class Set(models.Model):
    id = models.IntegerField(primary_key=True)
    player1 = models.ForeignKey(Player, models.DO_NOTHING, db_column='player1', blank=True, null=True)
    player2 = models.ForeignKey(Player, models.DO_NOTHING, db_column='player2', related_name='sets_player2_set', blank=True, null=True)
    player1score = models.IntegerField(blank=True, null=True)
    player2score = models.IntegerField(blank=True, null=True)
    winnerid = models.IntegerField(blank=True, null=True)
    tour = models.ForeignKey('Tournament', models.DO_NOTHING, blank=True, null=True)
    location = models.CharField(blank=True, null=True)
    played = models.BooleanField(blank=True, null=True)

    def __str__(self):
        return f"{self.player1} vs {self.player2} @ {self.tour} {self.location}"

    class Meta:
        managed = False
        db_table = 'set'


class Tournament(models.Model):
    tour_id = models.IntegerField(primary_key=True)
    name = models.CharField(blank=True, null=True)
    date = models.DateField(blank=True, null=True)
    region_code = models.ForeignKey(Region, models.DO_NOTHING, db_column='region_code', blank=True, null=True)
    entrant_count = models.IntegerField(blank=True, null=True)
    online = models.BooleanField(blank=True, null=True)
    type = models.CharField(blank=True, null=True)
    city = models.CharField(blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = 'tournament'


class TournamentResults(models.Model):
    tour = models.OneToOneField(Tournament, models.DO_NOTHING, primary_key=True)  # The composite primary key (tour_id, playerid) found, that is not supported. The first column is selected.
    playerid = models.ForeignKey(Player, models.DO_NOTHING, db_column='playerid')
    name = models.CharField(blank=True, null=True)
    placement = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tournament_results'
        unique_together = (('tour', 'playerid'),)
