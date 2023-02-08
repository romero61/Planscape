import datetime
import json
import numpy as np

from django.contrib.auth.models import User
from django.contrib.gis.gdal import GDALRaster
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from planscape import settings

from .models import Plan, Project, Scenario, ProjectArea, ConditionScores
from conditions.models import BaseCondition, Condition, ConditionRaster
from base.condition_types import ConditionLevel


class CreatePlanTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

    def test_missing_user(self):
        response = self.client.post(
            reverse('plan:create'), {'name': 'plan'},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_name(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'), {},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_geometry(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'), {'name': 'plan'},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_features(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'), {'name': 'plan', 'geometry': {}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_empty_features(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'geometry': {'features': []}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_bad_geometry(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'geometry': {'features': [
                {'type': 'Point', 'coordinates': [1, 2]}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_bad_polygon(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'geometry': {'features': [
                {'geometry': {'type': 'Polygon'}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_good_polygon(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'geometry': {'features': [
                {'geometry': {'type': 'Polygon', 'coordinates': [[[1, 2], [2, 3], [3, 4], [1, 2]]]}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Plan.objects.count(), 1)

    def test_good_multipolygon(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'geometry': {'features': [
                {'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Plan.objects.count(), 1)

    def test_bad_region_name(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'region_name': 'north_coast_inland', 'geometry': {'features': [
                {'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_good_region_name(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create'),
            {'name': 'plan', 'region_name': 'Northern California', 'geometry': {'features': [
                {'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        plans = Plan.objects.all()
        self.assertEqual(plans.count(), 1)
        plan = plans.first()
        assert plan is not None
        self.assertEqual(plan.region_name, 'north_coast_inland')


def create_plan(
        owner: User | None, name: str, geometry: GEOSGeometry | None,
        scenarios: list[int]):
    """
    Creates a plan with the given owner, name, geometry, and projects with the
    number of scenarios.
    """
    plan = Plan.objects.create(
        owner=owner, name=name, region_name='sierra_cascade_inyo',
        geometry=geometry)
    plan.save()
    for num_scenarios in scenarios:
        project = Project.objects.create(owner=owner, plan=plan)
        project.save()
        for _ in range(num_scenarios):
            scenario = Scenario.objects.create(project=project)
            scenario.save()
    return plan


class DeletePlanTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()
        self.plan1 = create_plan(None, "ownerless", None, [0])
        self.plan2 = create_plan(self.user, "owned", None, [1])
        self.plan3 = create_plan(self.user, "owned_also", None, [1, 2])

    def test_delete_user_not_logged_in(self):
        response = self.client.post(
            reverse('plan:delete'), {'id': self.plan2.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plan.objects.count(), 3)
        self.assertEqual(Project.objects.all().count(), 4)
        self.assertEqual(Scenario.objects.count(), 4)

    def test_user_logged_in_tries_to_delete_ownerless_plan(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:delete'), {'id': self.plan1.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plan.objects.count(), 3)
        self.assertEqual(Project.objects.count(), 4)
        self.assertEqual(Scenario.objects.count(), 4)

    def test_delete_wrong_user(self):
        new_user = User.objects.create(username='newuser')
        new_user.set_password('12345')
        new_user.save()
        self.client.force_login(new_user)
        response = self.client.post(
            reverse('plan:delete'), {'id': self.plan2.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plan.objects.count(), 3)
        self.assertEqual(Project.objects.count(), 4)
        self.assertEqual(Scenario.objects.count(), 4)

    def test_delete_ownerless_plan(self):
        self.assertEqual(Plan.objects.count(), 3)
        plan1_id = self.plan1.pk
        response = self.client.post(
            reverse('plan:delete'), {'id': self.plan1.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps(
            {"id": [self.plan1.pk]}).encode())
        self.assertEqual(Plan.objects.count(), 2)
        self.assertEqual(Project.objects.count(), 3)
        self.assertEqual(Scenario.objects.count(), 4)

    def test_delete_owned_plan(self):
        self.client.force_login(self.user)
        self.assertEqual(Plan.objects.count(), 3)
        response = self.client.post(
            reverse('plan:delete'), {'id': self.plan2.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps(
            {"id": [self.plan2.pk]}).encode())
        self.assertEqual(Plan.objects.count(), 2)
        self.assertEqual(Project.objects.count(), 3)
        self.assertEqual(Scenario.objects.count(), 3)

    def test_delete_multiple_plans_fails_if_any_not_owner(self):
        self.client.force_login(self.user)
        self.assertEqual(Plan.objects.count(), 3)
        plan_ids = [self.plan1.pk, self.plan2.pk]
        response = self.client.post(
            reverse('plan:delete'), {'id': plan_ids},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Plan.objects.count(), 3)
        self.assertEqual(Project.objects.count(), 4)
        self.assertEqual(Scenario.objects.count(), 4)

    def test_delete_multiple_plans(self):
        self.client.force_login(self.user)
        self.assertEqual(Plan.objects.count(), 3)
        plan_ids = [self.plan2.pk, self.plan3.pk]
        response = self.client.post(
            reverse('plan:delete'), {'id': plan_ids},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps(
            {"id": plan_ids}).encode())
        self.assertEqual(Plan.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(Scenario.objects.count(), 0)


class GetPlanTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()
        self.geometry = {'type': 'MultiPolygon',
                         'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}
        stored_geometry = GEOSGeometry(json.dumps(self.geometry))
        self.plan_no_user = create_plan(None, 'ownerless', stored_geometry, [])
        self.plan_with_user = create_plan(self.user, 'owned', None, [])

    def test_get_plan_with_user(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_plan'),
            {'id': self.plan_with_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'owned')
        self.assertEqual(response.json()['region_name'], 'Sierra Nevada')

    def test_get_nonexistent_plan(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('plan:get_plan'), {'id': 25},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_plan_does_not_belong_to_user(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_plan'),
            {'id': self.plan_no_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_plan_no_user(self):
        response = self.client.get(
            reverse('plan:get_plan'),
            {'id': self.plan_no_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'ownerless')
        self.assertEqual(response.json()['geometry'], self.geometry)
        self.assertLessEqual(
            response.json()['creation_timestamp'],
            round(datetime.datetime.now().timestamp()))
        self.assertEqual(response.json()['region_name'], 'Sierra Nevada')

    def test_get_plan_bad_stored_region(self):
        self.client.force_login(self.user)
        plan = Plan.objects.create(
            owner=self.user, name='badregion', region_name='Sierra Nevada',
            geometry=None)
        plan.save()
        response = self.client.get(reverse('plan:get_plan'), {'id': plan.pk},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'badregion')
        self.assertTrue(isinstance(response.json()['creation_timestamp'], int))
        self.assertLessEqual(
            response.json()['creation_timestamp'],
            round(datetime.datetime.now().timestamp()))
        self.assertEqual(response.json()['region_name'], None)


class ListPlansTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()
        self.geometry = {'type': 'MultiPolygon',
                         'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}
        stored_geometry = GEOSGeometry(json.dumps(self.geometry))
        self.plan1 = create_plan(None, 'plan1', None, [])
        self.plan2 = create_plan(None, 'plan2', stored_geometry, [0])
        self.plan3 = create_plan(self.user, 'plan3', stored_geometry, [1])
        self.plan4 = create_plan(self.user, 'plan4', stored_geometry, [2, 1])

    def test_list_plans_by_owner_no_user(self):
        response = self.client.get(reverse('plan:list_plans_by_owner'), {},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        for plan in response.json():
            self.assertTrue('geometry' not in plan)
            self.assertEqual(plan['region_name'], 'Sierra Nevada')
            if plan['name'] == 'plan1':
                self.assertEqual(plan['projects'], 0)
                self.assertEqual(plan['scenarios'], 0)
            elif plan['name'] == 'plan2':
                self.assertEqual(plan['projects'], 1)
                self.assertEqual(plan['scenarios'], 0)
            else:
                self.assertTrue(False)

    def test_list_plans_by_owner_no_user_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('plan:list_plans_by_owner'), {},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        for plan in response.json():
            self.assertTrue('geometry' not in plan)
            self.assertEqual(plan['region_name'], 'Sierra Nevada')
            if plan['name'] == 'plan3':
                self.assertEqual(plan['projects'], 1)
                self.assertEqual(plan['scenarios'], 1)
            elif plan['name'] == 'plan4':
                self.assertEqual(plan['projects'], 2)
                self.assertEqual(plan['scenarios'], 3)
            else:
                self.assertTrue(False)

    def test_list_plans_by_owner_with_user(self):
        response = self.client.get(
            reverse('plan:list_plans_by_owner'),
            {'owner': self.user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        for plan in response.json():
            self.assertTrue('geometry' not in plan)
            self.assertEqual(plan['region_name'], 'Sierra Nevada')
            if plan['name'] == 'plan3':
                self.assertEqual(plan['projects'], 1)
                self.assertEqual(plan['scenarios'], 1)
            elif plan['name'] == 'plan4':
                self.assertEqual(plan['projects'], 2)
                self.assertEqual(plan['scenarios'], 3)
            else:
                self.assertTrue(False)


class CreateProjectTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()
        self.plan_no_user = Plan.objects.create(
            owner=None, name='ownerless', region_name='sierra_cascade_inyo')
        self.plan_with_user = Plan.objects.create(
            owner=self.user, name='with_owner',
            region_name='sierra_cascade_inyo')

    def test_missing_user(self):
        response = self.client.post(
            reverse('plan:create_project'), {},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_plan(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create_project'), {},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_null_user_cannot_create_project_with_user(self):
        settings.PLANSCAPE_GUEST_CAN_SAVE = True
        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_with_user.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_user_cannot_create_project_with_null_user(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_no_user.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_no_user(self):
        settings.PLANSCAPE_GUEST_CAN_SAVE = True
        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_no_user.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_good_with_user(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_with_user.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_treatment_ratio_bad_format_negative(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_with_user.pk, 'max_treatment_area_ratio': -1},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_max_slope_bad_format_negative(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_with_user.pk, 'max_slope': -1},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_with_priority(self):
        self.client.force_login(self.user)
        self.base_condition = BaseCondition.objects.create(
            condition_name="condition1", condition_level=ConditionLevel.ELEMENT)
        self.condition1 = Condition.objects.create(
            condition_dataset=self.base_condition, condition_score_type=0)

        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_with_user.pk, 'priorities': 'condition1'},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_with_nonexistent_priority(self):
        self.client.force_login(self.user)
        self.base_condition = BaseCondition.objects.create(
            condition_name="base_condition", condition_level=ConditionLevel.ELEMENT)
        self.condition1 = Condition.objects.create(
            condition_dataset=self.base_condition, condition_score_type=0)

        response = self.client.post(
            reverse('plan:create_project'), {
                'plan_id': self.plan_with_user.pk, 'priorities': 'condition3'},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)


class UpdateProjectTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

        self.plan_with_user = Plan.objects.create(
            owner=self.user, name='with_owner', region_name='sierra_cascade_inyo')

        self.base_condition = BaseCondition.objects.create(
            condition_name="condition1", condition_level=ConditionLevel.ELEMENT)
        self.condition1 = Condition.objects.create(
            condition_dataset=self.base_condition)

        self.base_condition2 = BaseCondition.objects.create(
            condition_name="condition2", condition_level=ConditionLevel.ELEMENT)
        self.condition2 = Condition.objects.create(
            condition_dataset=self.base_condition2, condition_score_type=0)

        self.project_with_user = Project.objects.create(
            owner=self.user, plan=self.plan_with_user, max_budget=100.0)
        self.project_with_user.priorities.add(self.condition1)

    def test_wrong_http(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:update_project'), {}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_id(self):
        self.client.force_login(self.user)
        response = self.client.put(
            reverse('plan:update_project'), {}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_update_constraint_value_remove_priority(self):
        self.client.force_login(self.user)
        response = self.client.put(
            reverse('plan:update_project'), {
                'id': self.project_with_user.pk, 'max_budget': 200.0},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        project = Project.objects.get(id=self.project_with_user.pk)
        self.assertEqual(project.max_budget, 200.0)
        self.assertEqual(project.priorities.count(), 0)

    def test_remove_constraint_remove_priority(self):
        self.client.force_login(self.user)
        response = self.client.put(
            reverse('plan:update_project'), {'id': self.project_with_user.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        project = Project.objects.get(id=self.project_with_user.pk)
        self.assertEqual(project.max_budget, None)
        self.assertEqual(project.priorities.count(), 0)

    def test_add_constraint(self):
        self.client.force_login(self.user)
        response = self.client.put(
            reverse('plan:update_project'), {
                'id': self.project_with_user.pk, 'max_slope': 0.5},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        project = Project.objects.get(id=self.project_with_user.pk)
        self.assertEqual(project.max_budget, None)
        self.assertEqual(project.max_slope, 0.5)
        self.assertEqual(project.priorities.count(), 0)

    def test_add_priority(self):
        self.client.force_login(self.user)
        response = self.client.put(
            reverse('plan:update_project'), {'id': self.project_with_user.pk,
                                             'priorities': 'condition2'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        project = Project.objects.get(id=self.project_with_user.pk)
        self.assertEqual(project.max_budget, None)
        self.assertEqual(project.priorities.count(), 1)
        self.assertTrue(project.priorities.contains(self.condition2))


class DeleteProjectsTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

        self.plan_with_user = Plan.objects.create(
            owner=self.user, name='with_owner', region_name='sierra_cascade_inyo')
        self.plan_with_no_user = Plan.objects.create(
            owner=None, name='without owner', region_name='sierra_cascade_inyo')

        self.project_with_user = Project.objects.create(
            owner=self.user, plan=self.plan_with_user, max_budget=100.0)
        self.project_with_user2 = Project.objects.create(
            owner=self.user, plan=self.plan_with_user, max_budget=50.0)

        self.project_with_no_user = Project.objects.create(
            owner=None, plan=self.plan_with_no_user, max_budget=100.0)
    
    def test_delete_user_not_logged_in(self):
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': [self.project_with_user.pk]},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.all().count(), 3)

    def test_user_logged_in_tries_to_delete_ownerless_project(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': [self.project_with_no_user.pk]},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 3)

    def test_delete_wrong_user(self):
        new_user = User.objects.create(username='newuser')
        new_user.set_password('12345')
        new_user.save()
        self.client.force_login(new_user)
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': [self.project_with_user.pk]},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 3)

    def test_delete_ownerless_project(self):
        self.assertEqual(Project.objects.count(), 3)
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': [self.project_with_no_user.pk]},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps(
            [self.project_with_no_user.pk]).encode())
        self.assertEqual(Project.objects.count(), 2)

    def test_delete_owned_project(self):
        self.client.force_login(self.user)
        self.assertEqual(Project.objects.count(), 3)
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': [self.project_with_user.pk]},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps(
            [self.project_with_user.pk]).encode())
        self.assertEqual(Project.objects.count(), 2)

    def test_delete_multiple_projects_fails_if_any_not_owner(self):
        self.client.force_login(self.user)
        self.assertEqual(Project.objects.count(), 3)
        project_ids = [self.project_with_no_user.pk, self.project_with_user.pk]
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': project_ids},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 3)

    def test_delete_multiple_plans(self):
        self.client.force_login(self.user)
        self.assertEqual(Project.objects.count(), 3)
        project_ids = [self.project_with_user.pk, self.project_with_user2.pk]
        response = self.client.post(
            reverse('plan:delete_projects'), {'project_ids': project_ids},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps(
            project_ids).encode())
        self.assertEqual(Project.objects.count(), 1)


class CreateProjectAreaTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

        self.plan_no_user = Plan.objects.create(
            owner=None, name='ownerless', region_name='sierra_cascade_inyo')
        self.project_no_user = Project.objects.create(
            owner=None, plan=self.plan_no_user)

    # TODO: re-enable when we restrict functionality to logged in users
    # def test_missing_user(self):
    #     response = self.client.post(
    #         reverse('plan:create_project_area'), {'name': 'project_area'},
    #         content_type='application/json')
    #     self.assertEqual(response.status_code, 200)

    def test_missing_project(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_geometry(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {'project_id': self.project_no_user.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_missing_features(self):
        response = self.client.post(
            reverse('plan:create_project_area'), {
                'project_id': self.project_no_user.pk, 'geometry': {}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_empty_features(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {'project_id': self.project_no_user.pk, 'geometry': {'features': []}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_bad_geometry(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {'project_id': self.project_no_user.pk, 'geometry': {'features': [
                {'type': 'Point', 'coordinates': [1, 2]}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_bad_polygon(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {'project_id': self.project_no_user.pk, 'geometry': {'features': [
                {'geometry': {'type': 'Polygon'}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_good_polygon(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {'project_id': self.project_no_user.pk, 'geometry': {'features': [
                {'geometry': {'type': 'Polygon', 'coordinates': [[[1, 2], [2, 3], [3, 4], [1, 2]]]}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProjectArea.objects.count(), 1)

    def test_good_multipolygon(self):
        response = self.client.post(
            reverse('plan:create_project_area'),
            {'project_id': self.project_no_user.pk, 'geometry': {'features': [
                {'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}}]}},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProjectArea.objects.count(), 1)


class GetProjectTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

        self.geometry = {'type': 'MultiPolygon',
                         'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}
        stored_geometry = GEOSGeometry(json.dumps(self.geometry))

        self.plan_no_user = create_plan(None, 'ownerless', stored_geometry, [])
        self.project_no_user_no_pri = Project.objects.create(
            owner=None, plan=self.plan_no_user, max_budget=100)

        self.plan_with_user = create_plan(
            self.user, 'ownerless', stored_geometry, [])
        self.project_with_user_no_pri = Project.objects.create(
            owner=self.user, plan=self.plan_with_user, max_budget=100)

        self.base_condition = BaseCondition.objects.create(
            condition_name="name", condition_level=ConditionLevel.ELEMENT)
        self.condition1 = Condition.objects.create(
            condition_dataset=self.base_condition, raster_name="name1")
        self.condition2 = Condition.objects.create(
            condition_dataset=self.base_condition, raster_name="name2")

    def test_get_project_does_not_belong_to_user(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_project'),
            {'id': self.project_no_user_no_pri.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_project_no_user_no_priorities(self):
        response = self.client.get(
            reverse('plan:get_project'),
            {'id': self.project_no_user_no_pri.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['owner'], None)
        self.assertEqual(response.json()['plan'], self.plan_no_user.pk)
        self.assertEqual(response.json()['max_budget'], 100)

    def test_get_project_no_priorities(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_project'),
            {'id': self.project_with_user_no_pri.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['owner'], self.user.pk)
        self.assertEqual(response.json()['plan'], self.plan_with_user.pk)
        self.assertEqual(response.json()['max_budget'], 100)

    def test_get_nonexistent_project(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('plan:get_project'), {'id': 10},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_project_no_user_with_priorities(self):
        self.project_no_user_no_pri.priorities.add(self.condition1)
        self.project_no_user_no_pri.priorities.add(self.condition2)

        response = self.client.get(
            reverse('plan:get_project'),
            {'id': self.project_no_user_no_pri.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['owner'], None)
        self.assertEqual(response.json()['plan'], self.plan_no_user.pk)
        self.assertEqual(response.json()['max_budget'], 100)
        self.assertEqual(response.json()['priorities'], [
                         self.condition1.pk, self.condition2.pk])

    def test_get_project_with_priorities(self):
        self.client.force_login(self.user)
        self.project_with_user_no_pri.priorities.add(self.condition1)
        self.project_with_user_no_pri.priorities.add(self.condition2)

        response = self.client.get(
            reverse('plan:get_project'),
            {'id': self.project_with_user_no_pri.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['owner'], self.user.pk)
        self.assertEqual(response.json()['plan'], self.plan_with_user.pk)
        self.assertEqual(response.json()['max_budget'], 100)
        self.assertEqual(response.json()['priorities'], [
                         self.condition1.pk, self.condition2.pk])


class ListProjectsTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

        self.geometry = {'type': 'MultiPolygon',
                         'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}
        stored_geometry = GEOSGeometry(json.dumps(self.geometry))

        self.plan_with_user = create_plan(
            self.user, 'plan', stored_geometry, [])
        self.plan_without_user = create_plan(
            None, 'plan', stored_geometry, [])

    def test_list_no_plan_id(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:list_projects_for_plan'),
            {},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_list_no_matching_plan(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:list_projects_for_plan'),
            {'plan_id': 4},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_list_no_projects(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:list_projects_for_plan'),
            {'plan_id': self.plan_with_user.pk},
            content_type="application/json")
        print(response.content)
        self.assertEqual(response.status_code, 400)

    def test_list_projects(self):
        self.client.force_login(self.user)
        base_condition = BaseCondition.objects.create(
            condition_level=ConditionLevel.ELEMENT, display_name='test_condition')
        self.condition = Condition.objects.create(condition_dataset=base_condition)
        self.project_with_user = Project.objects.create(
            owner=self.user, plan=self.plan_with_user, max_budget=100)
        self.project_with_user.priorities.add(self.condition)

        response = self.client.get(
            reverse('plan:list_projects_for_plan'),
            {'plan_id': self.plan_with_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['id'], self.project_with_user.pk)
        self.assertEqual(response.json()[0]['priorities'], ['test_condition'])


class GetProjectAreaTest(TransactionTestCase):
    def setUp(self):
        self.geometry = {'type': 'MultiPolygon',
                         'coordinates': [[[[1, 2], [2, 3], [3, 4], [1, 2]]]]}
        stored_geometry = GEOSGeometry(json.dumps(self.geometry))

        self.base_condition = BaseCondition.objects.create(
            condition_name="name", condition_level=ConditionLevel.ELEMENT)
        self.condition1 = Condition.objects.create(
            condition_dataset=self.base_condition, raster_name="name1")
        self.condition2 = Condition.objects.create(
            condition_dataset=self.base_condition, raster_name="name2")

        self.plan_no_user = create_plan(None, 'ownerless', stored_geometry, [])
        self.project_no_user = Project.objects.create(
            owner=None, plan=self.plan_no_user, max_budget=100)
        self.project_area_no_user = ProjectArea.objects.create(
            owner=None, project=self.project_no_user,
            project_area=stored_geometry, estimated_area_treated=100)
        self.project_area_no_user2 = ProjectArea.objects.create(
            owner=None, project=self.project_no_user, project_area=stored_geometry)
        self.project_no_user_no_projectareas = Project.objects.create(
            owner=None, plan=self.plan_no_user, max_budget=200)

        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()
        self.plan_with_user = create_plan(
            self.user, 'ownerless', stored_geometry, [])
        self.project_with_user = Project.objects.create(
            owner=self.user, plan=self.plan_with_user, max_budget=100)
        self.project_area_with_user = ProjectArea.objects.create(
            owner=self.user, project=self.project_with_user,
            project_area=stored_geometry, estimated_area_treated=200)

    def test_get_project_does_not_belong_to_user(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_project_areas'),
            {'id': self.project_no_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_projectareas_for_nonexistent_project(self):
        response = self.client.get(
            reverse('plan:get_project_areas'),
            {'project_id': 10},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_projectareas_no_project_id(self):
        response = self.client.get(reverse('plan:get_project_areas'), {},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_get_projectareas_no_results(self):
        response = self.client.get(
            reverse('plan:get_project_areas'),
            {'project_id': self.project_no_user_no_projectareas.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 0)

    def test_get_projectareas_no_user(self):
        response = self.client.get(
            reverse('plan:get_project_areas'),
            {'project_id': self.project_no_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        project_area_id = str(self.project_area_no_user.pk)
        self.assertEqual(
            response.json()[project_area_id]['properties']['owner'], None)
        self.assertEqual(
            response.json()[project_area_id]['properties']['project'],
            self.project_no_user.pk)
        self.assertEqual(
            response.json()[project_area_id]['properties']['estimated_area_treated'], 100)
        self.assertEqual(
            response.json()[project_area_id]['geometry'], self.geometry)

    def test_get_projectareas_with_user(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_project_areas'),
            {'project_id': self.project_with_user.pk},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        project_area_id = str(self.project_area_with_user.pk)
        self.assertEqual(
            response.json()[project_area_id]['properties']['owner'],
            self.user.pk)
        self.assertEqual(
            response.json()[project_area_id]['properties']['project'],
            self.project_with_user.pk)
        self.assertEqual(
            response.json()[project_area_id]['properties']['estimated_area_treated'], 200)
        self.assertEqual(
            response.json()[project_area_id]['geometry'], self.geometry)


class GetScoresTest(TransactionTestCase):
    def setUp(self) -> None:
        # Add a row for CRS 9822 to the spatial_ref_sys table, and the GeoTiff to the table.
        # with connection.cursor() as cursor:
        #     query = ("insert into spatial_ref_sys(srid, proj4text) values(9822, '{}')").format(
        #         settings.CRS_9822_PROJ4)
        #     cursor.execute(query)

        self.user = User.objects.create(username='testuser')
        self.user.set_password('12345')
        self.user.save()

        self.region = 'sierra_cascade_inyo'

    def test_user_signed_in(self) -> None:
        self._set_up_db(self.user)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('plan:get_scores'),
            {'id': self.plan.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(response.json(), {'conditions': [
                             {'condition': 'foo', 'mean_score': 5.0}, {'condition': 'bar'}]})

    def test_user_not_signed_but_guests_can_save(self) -> None:
        settings.PLANSCAPE_GUEST_CAN_SAVE = True
        self._set_up_db(None)
        response = self.client.get(
            reverse('plan:get_scores'),
            {'id': self.plan.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(response.json(), {'conditions': [
                             {'condition': 'foo', 'mean_score': 5.0}, {'condition': 'bar'}]})

    def test_user_not_signed_and_guests_cant_save(self) -> None:
        settings.PLANSCAPE_GUEST_CAN_SAVE = False
        self._set_up_db(None)
        response = self.client.get(
            reverse('plan:get_scores'),
            {'id': self.plan.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def _create_condition_db(self, condition_name: str,
                             condition_raster_name: str) -> int:
        base_condition = BaseCondition.objects.create(
            condition_name=condition_name, region_name=self.region,
            condition_level=ConditionLevel.METRIC)
        condition = Condition.objects.create(
            raster_name=condition_raster_name,
            condition_dataset=base_condition, is_raw=False)
        ConditionRaster.objects.create(name=condition_raster_name)
        return condition.pk

    def _set_up_db(self, plan_owner: User) -> None:
        polygon = Polygon(
            ((-120, 40),
             (-120, 41),
             (-121, 41),
             (-121, 40),
             (-120, 40)))
        geo = MultiPolygon(polygon)
        geo.srid = 4269
        self.plan = create_plan(plan_owner, "my_plan", geo, [])

        foo_id = self._create_condition_db("foo", "foo_normalized")
        ConditionScores.objects.create(
            plan=self.plan, condition_id=foo_id, mean_score=5.0)

        bar_id = self._create_condition_db("bar", "bar_normalized")
        ConditionScores.objects.create(
            plan=self.plan, condition_id=bar_id, mean_score=None)
