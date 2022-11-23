from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.db import connection

import json, os

PLANSCAPE_ROOT_DIRECTORY = '/Users/jessxlee/cnra/'

# Name of the table and column from models.py.
RASTER_TABLE = 'condition_raster'
RASTER_COLUMN = 'raster'
RASTER_NAME_COLUMN = 'raster_name'


def get_wms(params: QueryDict):
    with connection.cursor() as cursor:
        # Get the width and height
        assert isinstance(params['width'], str)
        assert isinstance(params['height'], str)
        width = int(params['width'])
        height = int(params['height'])

        # Get the bounding box
        bbox = params['bbox']
        assert isinstance(bbox, str)
        bbox_coords = [float(c) for c in bbox.split(',')]

        # Get the SRID
        assert isinstance(params['srs'], str)
        srid = int(params['srs'].removeprefix('EPSG:'))

        # See ST_ColorMap documentation for format.
        colormap = 'fire'
        cursor.callproc('get_rast_tile', (params['format'], width, height, srid,
                        bbox_coords[0], bbox_coords[1], bbox_coords[2], bbox_coords[3],
                        colormap, 'public', RASTER_TABLE, RASTER_COLUMN, RASTER_NAME_COLUMN,
                        params['layers']))
        row = cursor.fetchone()
    return row

def get_region(params: QueryDict):
    # Get region name
    assert isinstance(params['region_name'], str)
    region_name = params['region_name']
    print(region_name)

    # Read from conditions config
    config_path = os.path.join(
       PLANSCAPE_ROOT_DIRECTORY, 'Planscape/src/planscape/config/conditions.json')
    conditions_config = json.load(open(config_path, 'r'))

    # Extract specific region data from JSON
    for region in conditions_config['regions']:
        print(region)
        if region_name == region['region_name']:
            return region

    return None

def wms(request: HttpRequest) -> HttpResponse:
    image = get_wms(request.GET)
    return HttpResponse(image, content_type=request.GET['format'])

def regions(request: HttpRequest) -> HttpResponse :
    region = get_region(request.GET)
    return JsonResponse(region)
