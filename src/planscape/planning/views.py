import json
import os


from base.region_name import display_name_to_region, region_to_display_name
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.sites.shortcuts import get_current_site
from django.db import IntegrityError
from django.db.models import Count, Max
from django.db.models.functions import Coalesce

from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    Http404,
    JsonResponse,
    QueryDict,
)
from django.shortcuts import get_object_or_404
from pathlib import Path
from planning.models import (
    PlanningArea,
    Scenario,
    ScenarioResult,
    ScenarioResultStatus,
    SharedLink,
)
from planning.serializers import (
    PlanningAreaSerializer,
    ScenarioSerializer,
    SharedLinkSerializer,
)
from planning.services import (
    export_to_shapefile,
    validate_scenario_treatment_ratio,
    zip_directory,
)
from planning.tasks import async_forsys_run
from urllib.parse import urljoin
from utils.cli_utils import call_forsys


# Retrieve the logged in user from the HTTP request.
def _get_user(request: HttpRequest) -> User:
    user = None
    if hasattr(request, "user") and request.user.is_authenticated:
        user = request.user
    return user


# We always need to store multipolygons, so coerce a single polygon to
# a multigolygon if needed.
def _convert_polygon_to_multipolygon(geometry: dict):
    features = geometry.get("features", [])
    if len(features) > 1 or len(features) == 0:
        raise ValueError("Must send exactly one feature.")
    feature = features[0]
    geom = feature["geometry"]
    if geom["type"] == "Polygon":
        geom["type"] = "MultiPolygon"
        geom["coordinates"] = [feature["geometry"]["coordinates"]]
    actual_geometry = GEOSGeometry(json.dumps(geom))
    if actual_geometry.geom_type != "MultiPolygon":
        raise ValueError("Could not parse geometry")
    return actual_geometry


# TODO: Along with PlanningAreaSerializer, refactor this a bit more to
# make it more maintainable.
def _serialize_planning_area(planning_area: PlanningArea, add_geometry: bool) -> dict:
    """
    Serializes a Planning Area (Plan) into a dictionary.
    1. Converts the Planning Area to a dictionary with fields 'id', 'geometry', and 'properties'
       (the latter of which is a dictionary).
    2. Creates the partial result from the properties and 'id' fields.
    3. Adds the 'geometry' if requested.
    4. Replaces the internal region_name with the display version.
    """
    data = PlanningAreaSerializer(planning_area).data
    result = data["properties"]
    result["id"] = data["id"]
    if "geometry" in data and add_geometry:
        result["geometry"] = data["geometry"]
    if "region_name" in result:
        result["region_name"] = region_to_display_name(result["region_name"])
    return result


#### PLAN(NING AREA) Handlers ####
def create_planning_area(request: HttpRequest) -> HttpResponse:
    """
    Creates a planning area (aka plan), given a name, region, an optional geometry,
    and an optional notes string.
    Requires a logged in user.

    Returns: id: the newly inserted planning area's primary key (int)

    Required params:
      name (str): User-provided name of the planning area.
      region_name (str): The region name, in user-facing form, e.g. "Sierra Nevada"
      geometry (JSON str): The planning area shape, in GEOGeometry-compatible JSON.
         This can be '{}', but the param does need to be specified.

    Optional params:
      notes (str): An optional note string for this planning area.
    """
    try:
        # Check that the user is logged in.
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        # Get the name of the planning area.
        body = json.loads(request.body)
        name = body.get("name")
        if name is None:
            raise ValueError("Must specify a planning area name.")

        # Get the region name; it should be in the human-readable display name format.
        region_name_input = body.get("region_name")
        if region_name_input is None:
            raise ValueError("Region name must be specified.")

        region_name = display_name_to_region(region_name_input)
        if region_name is None:
            raise ValueError("Unknown region_name: " + region_name_input)

        # Get the geometry of the planning area.
        geometry = body.get("geometry")
        if geometry is None:
            raise ValueError("Must specify the planning area geometry.")

        # Convert to a MultiPolygon if it is a simple Polygon, since the model column type is
        # MultiPolygon.
        geometry = _convert_polygon_to_multipolygon(geometry)

        # Create the planning area
        planning_area = PlanningArea.objects.create(
            user=user,
            name=name,
            region_name=region_name,
            geometry=geometry,
            notes=body.get("notes", None),
        )
        planning_area.save()

        return HttpResponse(
            json.dumps({"id": planning_area.pk}), content_type="application/json"
        )

        return HttpResponse(str(planning_area.pk))
    except Exception as e:
        return HttpResponseBadRequest("Error in create: " + str(e))


def delete_planning_area(request: HttpRequest) -> HttpResponse:
    """
    Deletes a planning area or areas.
    Requires a logged in user.  Users can delete only their owned planning areas.
    Deletion of a planning area not owned by the user will not generate an error but will not delete anything.
    Deletion attempts of nonexistent planning areas will not generate an error but will also not delete anything.

    Returns: The list of IDs entered, including those IDs that failed to matched a user-owned planning area.

    Required params:
      id (int): id: the ID of the planning area to delete, or a list of IDs to delete.
    """
    try:
        # Check that the user is logged in.
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        # Get the planning area IDs
        body = json.loads(request.body)
        planning_area_id = body.get("id", None)
        planning_area_ids = []
        if planning_area_id is None:
            raise ValueError("Must specify planning area id.")
        elif isinstance(planning_area_id, int):
            planning_area_ids = [planning_area_id]
        elif isinstance(planning_area_id, list):
            planning_area_ids = planning_area_id
        else:
            raise ValueError("Planning Area ID must be an int or a list of ints.")

        # Get the planning area(s) for just the logged in user.
        planning_areas = user.planning_areas.filter(pk__in=planning_area_ids)

        planning_areas.delete()

        # We still report that the full set of planning area IDs requested were deleted,
        # since from the user's perspective, there are no planning areas with that ID.
        # The end result is that those planning areas don't exist as far as the user is concerned.
        response_data = {"id": planning_area_ids}

        return HttpResponse(json.dumps(response_data), content_type="application/json")
    except Exception as e:
        return HttpResponseBadRequest("Error in delete: " + str(e))


def update_planning_area(request: HttpRequest) -> HttpResponse:
    """
    Updates a planning area's name or notes.  To date, these are the only fields that
    can be modified after a planning area is created.  This can be also used to clear
    the notes field, but the name needs to be defined always.

    Calling this without anything to update will not throw an error.

    Requires a logged in user.  Users can modify only their owned planning_areas.

    Returns: id: The planning area's ID, even if nothing needed updating.

    Required params:
      id (int): ID of the planning area to retrieve.
    """
    try:
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        body = json.loads(request.body)
        planning_area_id = body.get("id", None)
        planning_area = get_object_or_404(user.planning_areas, id=planning_area_id)
        is_dirty = False

        if "notes" in body:
            # This can clear the notes field
            planning_area.notes = body.get("notes")
            is_dirty = True

        if "name" in body:
            # This must be always defined
            new_name = body.get("name")
            if (new_name is None) or (len(new_name) == 0):
                raise ValueError("name must be defined")
            planning_area.name = new_name
            is_dirty = True

        if is_dirty:
            planning_area.save()

        return HttpResponse(
            json.dumps({"id": planning_area_id}), content_type="application/json"
        )
    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e))


def get_planning_area_by_id(request: HttpRequest) -> HttpResponse:
    """
    Retrieves a planning area by ID.
    Requires a logged in user.  Users can see only their owned planning_areas.

    Returns: The planning area in JSON form.  The JSON will also include two metadata fields:
      scenario_count: number of scenarios for this planning area.
      latest_updated: latest datetime (e.g. 2023-09-08T20:33:28.090393Z) across all scenarios or
        PlanningArea updated_at if no scenarios

    Required params:
      id (int): ID of the planning area to retrieve.
    """
    try:
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")
        user_id = user.pk

        return JsonResponse(
            _serialize_planning_area(
                get_object_or_404(
                    user.planning_areas.annotate(
                        scenario_count=Count("scenarios", distinct=True)
                    ).annotate(scenario_latest_updated_at=Max("scenarios__updated_at")),
                    id=request.GET["id"],
                ),
                True,
            )
        )
    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e))


# No Params expected, since we're always using the logged in user.
def list_planning_areas(request: HttpRequest) -> HttpResponse:
    """
    Retrieves all planning areas for a user.
    Requires a logged in user.  Users can see only their owned planning_areas.

    Returns: A list of planning areas in JSON form.  Each planning area JSON will also include
        two metadata fields:
      scenario_count: number of scenarios for the planning area returned.
      latest_updated: latest datetime (e.g. 2023-09-08T20:33:28.090393Z) across all scenarios or
        PlanningArea updated_at if no scenarios

    Required params: none
    """
    try:
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")
        user_id = user.pk

        # TODO: This could be really slow; consider paging or perhaps
        # fetching everything but geometries (since they're huge) for performance gains.
        # given that we need geometry to calculate total acres, should we save this value
        # when creating the planning area instead of calculating it each time?

        planning_areas = (
            PlanningArea.objects.filter(user=user_id)
            .annotate(scenario_count=Count("scenarios", distinct=True))
            .annotate(
                scenario_latest_updated_at=Coalesce(
                    Max("scenarios__updated_at"), "updated_at"
                )
            )
            .order_by("-scenario_latest_updated_at")
        )
        return JsonResponse(
            [
                _serialize_planning_area(planning_area, True)
                for planning_area in planning_areas
            ],
            safe=False,
        )
    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e))


def _serialize_scenario(scenario: Scenario) -> dict:
    """
    Serializes a Scenario into a dictionary.
    # TODO: Add more logic here as our Scenario model expands beyond just the
    #       JSON "configuration" field.
    """
    data = ScenarioSerializer(scenario).data
    return data


def get_scenario_by_id(request: HttpRequest) -> HttpResponse:
    """
    Retrieves a scenario by its ID.
    Requires a logged in user.  Users can see only scenarios belonging to their own planning areas.

    Returns: A scenario in JSON form.

    Required params:
      id (int): The scenario ID to be retrieved.
    """
    try:
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        scenario = Scenario.objects.select_related("planning_area__user").get(
            id=request.GET["id"]
        )
        if scenario.planning_area.user.pk != user.pk:
            # This matches the same error string if the planning area doesn't exist in the DB for any user.
            raise ValueError("Scenario matching query does not exist.")
        return JsonResponse(_serialize_scenario(scenario), safe=False)
    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e))


def download_csv(request: HttpRequest) -> HttpResponse:
    """
    Generates a new Zip file for a scenario based on ID.

    Requires a logged in user.  Users can only access a scenarios belonging to their own planning areas.

    Returns: a Zip file generated with the CSVs ad JSON file for this particular scenario

    Required params:
      id (int): The scenario ID to be retrieved.

    TODO: maybe generate a unique key and store that for each output dir name when we create it?
    """
    # Ensure that the user is logged in.
    user = _get_user(request)
    if user is None:
        return HttpResponse(
            "Unauthorized. User is not logged in.",
            status=401,
        )

    scenario = (
        Scenario.objects.select_related("planning_area__user")
        .filter(id=request.GET["id"])
        .first()
    )

    if not scenario:
        return HttpResponse(
            "Scenario matching query does not exist.",
            status=404,
        )

    # Ensure that current user is associated with this scenario
    if scenario.planning_area.user.pk != user.pk:
        return HttpResponse(
            "Scenario matching query does not exist.",
            status=404,
        )

    scenario_result = ScenarioResult.objects.get(scenario__id=scenario.pk)

    try:
        output_zip_name: str = str(scenario.uuid) + ".zip"

        if not scenario.get_forsys_folder().exists():
            raise ValueError("Scenario files cannot be read.")

        response = HttpResponse(content_type="application/zip")
        #  here we're just writing directly to the response obj.
        # Do we want to write this locally -- either to (effectively) cache it, or to reduce server memory load?
        # Note that we don't close this, because `response` gets destroyed on its own
        zip_directory(response, scenario.get_forsys_folder())

        response["Content-Disposition"] = f"attachment; filename={output_zip_name}"
        return response

    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e), status=400)


def download_shapefile(request: HttpRequest) -> HttpResponse:
    """
    Generates a new Zip file of the shapefile for a scenario based on ID.

    Requires a logged in user.  Users can only access a scenarios belonging to their own planning areas.

    Returns: a Zip file generated with the shapefiles

    Required params:
      id (int): The scenario ID to be retrieved.
    """
    # Ensure that the user is logged in.
    user = _get_user(request)
    if user is None:
        return HttpResponse(
            "Unauthorized. User is not logged in.",
            status=401,
        )

    scenario = Scenario.objects.select_related("planning_area__user").get(
        id=request.GET["id"]
    )
    # Ensure that current user is associated with this scenario
    if scenario.planning_area.user.pk != user.pk:
        return HttpResponse(
            "Scenario does not exist.",
            status=404,
        )

    scenario_result = ScenarioResult.objects.get(scenario__id=scenario.pk)
    if scenario_result.status != ScenarioResultStatus.SUCCESS:
        return HttpResponse(
            "Scenario was not successful, can't download data.",
            status=424,
        )

    try:
        output_zip_name = f"{str(scenario.uuid)}.zip"
        export_to_shapefile(scenario)
        response = HttpResponse(content_type="application/zip")
        zip_directory(response, scenario.get_shapefile_folder())

        response["Content-Disposition"] = f"attachment; filename={output_zip_name}"
        return response

    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e), status=400)


def create_scenario(request: HttpRequest) -> HttpResponse:
    """
    Creates a Scenario.  This also creates a default (e.g. mostly empty) ScenarioResult associated with the scenario.
    Requires a logged in user, as a scenario must be associated with a user's planning area.

    Returns: id: the ID of the newly inserted Scenario.

    Required params:
      name (str): The user-provided name of the Scenario.
      planning_area (int): The ID of the planning area that will recieve the new Scenario.
      configuration (str): A JSON string representing the scenario configuration (e.g. query parameters, weights).

    Optional params:
      notes (str): User-provided notes for this scenario.
    """
    try:
        # Check that the user is logged in.
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        body = json.loads(request.body)

        # Check for all needed fields
        serializer = ScenarioSerializer(data=body)
        serializer.is_valid(raise_exception=True)

        # Ensure that we have a viable planning area owned by the user.  Note that this gives a slightly different
        # error response for a nonowned planning area vs. when given a nonexistent planning area.
        planning_area = get_object_or_404(user.planning_areas, id=body["planning_area"])

        # TODO: Parse configuration field into further components.
        result, reason = validate_scenario_treatment_ratio(
            planning_area,
            serializer.validated_data.get("configuration"),
        )

        if not result:
            return HttpResponse(
                json.dumps({"reason": reason}),
                content_type="application/json",
                status=400,
            )

        scenario = serializer.save()

        # Create a default scenario result.
        # Note that if this fails, we will have still written the Scenario without
        # a corresponding ScenarioResult.
        scenario_result = ScenarioResult.objects.create(scenario=scenario)
        scenario_result.save()

        if settings.USE_CELERY_FOR_FORSYS:
            async_forsys_run.delay(scenario.pk)

        return JsonResponse({"id": scenario.pk})

    except IntegrityError as ve:
        reason = ve.args[0]
        if "(planning_area_id, name)" in ve.args[0]:
            reason = "A scenario with this name already exists."
        return HttpResponse(
            json.dumps({"reason": reason}),
            content_type="application/json",
            status=400,
        )
    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e))


def update_scenario(request: HttpRequest) -> HttpResponse:
    """
    Updates a scenario's name or notes.  To date, these are the only fields that
    can be modified after a scenario is created.  This can be also used to clear
    the notes field, but the name needs to be defined always.

    Calling this without anything to update will not throw an error.

    Requires a logged in user.  Users can modify only their owned scenarios.

    Returns: id: The scenario's ID, even if nothing needed updating.

    Required params:
      id (int): ID of the scenario to retrieve.
    """
    try:
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        body = json.loads(request.body)
        scenario_id = body.get("id", None)
        if scenario_id is None:
            raise ValueError("Scenario ID is required.")

        scenario = Scenario.objects.select_related("planning_area__user").get(
            id=scenario_id
        )
        if scenario.planning_area.user.pk != user.pk:
            # This matches the same error string if the planning area doesn't exist in the DB for any user.
            raise ValueError("Scenario matching query does not exist.")

        is_dirty = False

        if "notes" in body:
            # This can clear the notes field
            scenario.notes = body.get("notes")
            is_dirty = True

        if "name" in body:
            # This must be always defined
            new_name = body.get("name")
            if (new_name is None) or (len(new_name) == 0):
                raise ValueError("name must be defined")
            scenario.name = new_name
            is_dirty = True

        if is_dirty:
            scenario.save()

        return HttpResponse(
            json.dumps({"id": scenario_id}), content_type="application/json"
        )
    except Exception as e:
        return HttpResponseBadRequest("Ill-formed request: " + str(e))


# TODO: add more things to update other than state
# Unlike other routines, this does not require a user login context, as it is expected to be called
# by the EP.
#
# TODO: require credential from EP so that random people cannot call this endpoint.
def update_scenario_result(request: HttpRequest) -> HttpResponse:
    """
    Updates a ScenarioResult's status.
    Requires a logged in user, as a scenario must be associated with a user's planning area.
    Throws an error if no scenario/ScenarioResult owned by the user can be found with the desired ID.
    This does not modify the Scenario object itself.
    A ScenarioResult's status can be updated only in the following directions:
       PENDING -> RUNNING | FAILURE
       RUNNING -> SUCCESS | FAILURE

    Returns: id: the ID of the Scenario whose ScenarioResult was updated.

    Required params:
      scenario_id (int): The scenario ID whose ScenarioResult is meant to be updated.

    Optional params:
      status (ScenarioResultStatus): The new status of the ScenarioResult.
      result (JSON str): Details of the run.
      run_details (JSON str): Even more verbose details of the run.
    """
    try:
        body = json.loads(request.body)
        scenario_id = body.get("scenario_id")

        scenario_result = ScenarioResult.objects.get(scenario__id=scenario_id)

        new_status = body.get("status")
        old_status = scenario_result.status

        if new_status is not None:
            match new_status:
                case ScenarioResultStatus.RUNNING:
                    if old_status != ScenarioResultStatus.PENDING:
                        raise ValueError("Invalid new state.")
                case ScenarioResultStatus.SUCCESS:
                    if old_status != ScenarioResultStatus.RUNNING:
                        raise ValueError("Invalid new state.")
                case _:
                    if new_status != ScenarioResultStatus.FAILURE:
                        raise ValueError("Invalid new state.")
            scenario_result.status = new_status

        if (run_details := body.get("run_details")) is not None:
            scenario_result.run_details = run_details

        if (result := body.get("result")) is not None:
            scenario_result.result = result

        scenario_result.save()

        return HttpResponse(
            json.dumps({"id": scenario_id}), content_type="application/json"
        )
    except Exception as e:
        return HttpResponseBadRequest("Update Scenario error: " + str(e))


def list_scenarios_for_planning_area(request: HttpRequest) -> HttpResponse:
    """
    Lists all Scenarios for a Planning area.
    Requires a logged in user, as a scenario must be associated with a user's planning area.

    Returns: a list of the scenarios for the user.  Will return an empty list
      if given a planning area that has no scenarios, a planning area that isn't owned by the user,
      or if there is no existing planning area associated with the given planning area ID.

    Required params:
      planning_area (int): The planning area ID whose scenarios to retrieve.
    """
    try:
        # Check that the user is logged in.
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        planning_area_id = request.GET["planning_area"]
        if planning_area_id is None:
            raise ValueError("Missing planning_area")

        scenarios = Scenario.objects.filter(planning_area__user_id=user.pk).filter(
            planning_area__pk=planning_area_id
        )
        return JsonResponse(
            [_serialize_scenario(scenario) for scenario in scenarios], safe=False
        )
    except Exception as e:
        return HttpResponseBadRequest("List Scenario error: " + str(e))


def delete_scenario(request: HttpRequest) -> HttpResponse:
    """
    Deletes a scenario or list of scenarios for a planning_area owned by the user.
    Requires a logged in user, as a scenario must be associated with a user's planning area.
    Scenarios that do not exist or do not belong to a planning_area that is owned by the user
    will appear in the returned list, but scenarios that are not owned by the user are not changed.

    Returns: id: the list of IDs to be deleted.

    Required params:
      scenario_id (int): The ID of the scenario (or list of IDs) to delete.
    """
    try:
        # Check that the user is logged in.
        user = _get_user(request)
        if user is None:
            raise ValueError("User must be logged in.")

        body = json.loads(request.body)
        scenario_id_str = body.get("scenario_id", None)
        if scenario_id_str is None:
            raise ValueError("Must specify scenario id(s)")

        scenario_ids = []
        if isinstance(scenario_id_str, int):
            scenario_ids = [scenario_id_str]
        elif isinstance(scenario_ids, list):
            scenario_ids = scenario_id_str
        else:
            raise ValueError("scenario_id must be an int or a list of ints.")

        # Get the scenarios matching the provided IDs and the logged-in user.
        scenarios = Scenario.objects.filter(pk__in=scenario_ids).filter(
            planning_area__user=user.pk
        )
        # This automatically deletes ScenarioResult entries for the deleted Scenarios.
        scenarios.delete()

        # We still report that the full set of scenario IDs requested were deleted,
        # since from the user's perspective, there are no scenarios with that ID after this
        # call completes.
        response_data = {"id": scenario_ids}

        return HttpResponse(json.dumps(response_data), content_type="application/json")
    except Exception as e:
        return HttpResponseBadRequest("Delete Scenario error: " + str(e))


def get_treatment_goals_config_for_region(params: QueryDict):
    # Get region name
    assert isinstance(params["region_name"], str)
    region_name = params["region_name"]

    # Read from treatment_goals config
    config_path = os.path.join(settings.BASE_DIR, "config/treatment_goals.json")
    treatment_goals_config = json.load(open(config_path, "r"))
    for region in treatment_goals_config["regions"]:
        if region_name == region["region_name"]:
            return region["treatment_goals"]

    return None


def treatment_goals_config(request: HttpRequest) -> HttpResponse:
    treatment_goals = get_treatment_goals_config_for_region(request.GET)
    return JsonResponse(treatment_goals, safe=False)


#### SHARED LINK Handlers ####
def get_shared_link(request: HttpRequest, link_code: str) -> HttpResponse:
    try:
        link_obj = SharedLink.objects.get(link_code=link_code)
    except SharedLink.DoesNotExist:
        # Handle the case where the object doesn't exist
        raise Http404("This link does not exist")
    serializer = SharedLinkSerializer(link_obj)
    return JsonResponse(serializer.data, safe=False)


def create_shared_link(request: HttpRequest) -> HttpResponse:
    try:
        user = _get_user(request)
        body = json.loads(request.body)
        serializer = SharedLinkSerializer(data=body, context={"user": user})
        serializer.is_valid(raise_exception=True)
        shared_link = serializer.save()

        serializer = SharedLinkSerializer(shared_link)
        return JsonResponse(serializer.data)

    except Exception as e:
        return HttpResponseBadRequest("Error in create: " + str(e))
