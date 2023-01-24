import { NestedTreeControl } from '@angular/cdk/tree';
import {
  AfterViewInit,
  ApplicationRef,
  Component,
  createComponent,
  EnvironmentInjector,
  OnDestroy,
  OnInit,
} from '@angular/core';
import { MatDialog, MatDialogConfig } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { Router } from '@angular/router';
import { Feature, Geometry } from 'geojson';
import { BehaviorSubject, Observable, Subject, take, takeUntil } from 'rxjs';
import { filter, switchMap } from 'rxjs/operators';
import * as shp from 'shpjs';

import {
  MapService,
  PlanService,
  PlanState,
  PopupService,
  SessionService,
} from '../services';
import {
  BaseLayerType,
  BoundaryConfig,
  colormapConfigToLegend,
  ConditionsConfig,
  DataLayerConfig,
  DEFAULT_COLORMAP,
  defaultMapConfig,
  defaultMapViewOptions,
  Legend,
  Map,
  MapConfig,
  MapViewOptions,
  NONE_BOUNDARY_CONFIG,
  NONE_COLORMAP,
  NONE_DATA_LAYER_CONFIG,
  Region,
} from '../types';
import { MapManager } from './map-manager';
import { PlanCreateDialogComponent } from './plan-create-dialog/plan-create-dialog.component';
import { ProjectCardComponent } from './project-card/project-card.component';

export enum AreaCreationAction {
  NONE = 0,
  DRAW = 1,
  UPLOAD = 2,
}

export interface ConditionsNode extends DataLayerConfig {
  showInfoIcon?: boolean;
  infoMenuOpen?: boolean;
  disableSelect?: boolean; // Node should not include a radio button
  styleDisabled?: boolean; // Node should be greyed out but still selectable
  children?: ConditionsNode[];
}

@Component({
  selector: 'app-map',
  templateUrl: './map.component.html',
  styleUrls: ['./map.component.scss'],
})
export class MapComponent implements AfterViewInit, OnDestroy, OnInit {
  mapManager: MapManager;

  maps: Map[];
  mapViewOptions$ = new BehaviorSubject<MapViewOptions>(
    defaultMapViewOptions()
  );
  mapNameplateWidths: BehaviorSubject<number | null>[] = Array(4)
    .fill(null)
    .map((_) => new BehaviorSubject<number | null>(null));

  boundaryConfig$: Observable<BoundaryConfig[] | null>;
  conditionsConfig$: Observable<ConditionsConfig | null>;
  selectedRegion$: Observable<Region | null>;
  planState$: Observable<PlanState>;

  readonly noneBoundaryConfig = NONE_BOUNDARY_CONFIG;

  readonly baseLayerTypes: number[] = [
    BaseLayerType.Road,
    BaseLayerType.Terrain,
  ];
  readonly BaseLayerType = BaseLayerType;

  existingProjectsGeoJson$ = new BehaviorSubject<GeoJSON.GeoJSON | null>(null);

  loadingIndicators: { [layerName: string]: boolean } = {
    existing_projects: true,
  };

  legend: Legend = {
    labels: [
      'Highest',
      'Higher',
      'High',
      'Mid-high',
      'Mid-low',
      'Low',
      'Lower',
      'Lowest',
    ],
    colors: [
      '#f65345',
      '#e9884f',
      '#e5ab64',
      '#e6c67a',
      '#cccfa7',
      '#a5c5a6',
      '#74afa5',
      '#508295',
    ],
  };

  /** Actions bar variables */
  readonly AreaCreationAction = AreaCreationAction;
  showUploader = false;
  showAreaCreationActionButtons = false;
  selectedAreaCreationAction: AreaCreationAction = AreaCreationAction.NONE;
  showConfirmAreaButton$ = new BehaviorSubject(false);

  conditionTreeControl = new NestedTreeControl<ConditionsNode>(
    (node) => node.children
  );
  conditionDataSource = new MatTreeNestedDataSource<ConditionsNode>();

  private readonly destroy$ = new Subject<void>();

  constructor(
    public applicationRef: ApplicationRef,
    private mapService: MapService,
    private dialog: MatDialog,
    private matSnackBar: MatSnackBar,
    private environmentInjector: EnvironmentInjector,
    private popupService: PopupService,
    private sessionService: SessionService,
    private planService: PlanService,
    private router: Router
  ) {
    this.boundaryConfig$ = this.mapService.boundaryConfig$.pipe(
      takeUntil(this.destroy$)
    );
    this.conditionsConfig$ = this.mapService.conditionsConfig$.pipe(
      takeUntil(this.destroy$)
    );
    this.selectedRegion$ = this.sessionService.region$.pipe(
      takeUntil(this.destroy$)
    );
    this.planState$ = this.planService.planState$.pipe(
      takeUntil(this.destroy$)
    );

    this.mapService
      .getExistingProjects()
      .pipe(takeUntil(this.destroy$))
      .subscribe((projects: GeoJSON.GeoJSON) => {
        this.existingProjectsGeoJson$.next(projects);
        this.loadingIndicators['existing_projects'] = false;
      });

    this.maps = ['map1', 'map2', 'map3', 'map4'].map(
      (id: string, index: number) => {
        return {
          id: id,
          name: 'Map ' + (index + 1),
          config: defaultMapConfig(),
        };
      }
    );

    this.mapManager = new MapManager(
      matSnackBar,
      this.maps,
      this.mapViewOptions$,
      popupService,
      this.startLoadingLayerCallback.bind(this),
      this.doneLoadingLayerCallback.bind(this)
    );
    this.mapManager.polygonsCreated$
      .pipe(takeUntil(this.destroy$))
      .subscribe(this.showConfirmAreaButton$);

    this.conditionDataSource.data = [NONE_DATA_LAYER_CONFIG];
    this.conditionsConfig$
      .pipe(filter((config) => !!config))
      .subscribe((config) => {
        this.conditionDataSource.data = this.conditionsConfigToData(config!);
        this.maps.forEach((map) => {
          // Ensure the radio button corresponding to the saved selection is selected.
          map.config.dataLayerConfig = this.findAndRevealNodeWithFilepath(
            map.config.dataLayerConfig.filepath
          );
        });
      });
  }

  ngOnInit(): void {
    this.restoreSession();
    /** Save map configurations in the user's session every X ms. */
    this.sessionService.sessionInterval$
      .pipe(takeUntil(this.destroy$))
      .subscribe((_) => {
        this.sessionService.setMapViewOptions(this.mapViewOptions$.getValue());
        this.sessionService.setMapConfigs(
          this.maps.map((map: Map) => map.config)
        );
      });
  }

  ngAfterViewInit(): void {
    this.maps.forEach((map: Map) => {
      this.initMap(map, map.id);
    });
    this.mapManager.syncAllMaps();
  }

  ngOnDestroy(): void {
    this.maps.forEach((map: Map) => map.instance?.remove());
    this.sessionService.setMapConfigs(this.maps.map((map: Map) => map.config));
    this.destroy$.next();
    this.destroy$.complete();
  }

  private restoreSession() {
    this.sessionService.mapViewOptions$
      .pipe(take(1))
      .subscribe((mapViewOptions: MapViewOptions | null) => {
        if (mapViewOptions) {
          this.mapViewOptions$.next(mapViewOptions);
        }
      });
    this.sessionService.mapConfigs$
      .pipe(take(1))
      .subscribe((mapConfigs: MapConfig[] | null) => {
        if (mapConfigs) {
          mapConfigs.forEach((mapConfig, index) => {
            this.maps[index].config = mapConfig;
          });
        }
        this.boundaryConfig$
          .pipe(filter((config) => !!config))
          .subscribe((config) => {
            // Ensure the radio button corresponding to the saved selection is selected.
            this.maps.forEach((map) => {
              const boundaryConfig = config?.find(
                (boundary) =>
                  boundary.boundary_name ===
                  map.config.boundaryLayerConfig.boundary_name
              );
              map.config.boundaryLayerConfig = boundaryConfig
                ? boundaryConfig
                : NONE_BOUNDARY_CONFIG;
            });
          });
      });
  }

  /** Initializes the map with controls and the layer options specified in its config. */
  private initMap(map: Map, id: string) {
    this.mapManager.initLeafletMap(
      map,
      id,
      this.existingProjectsGeoJson$,
      this.createDetailCardCallback.bind(this),
      this.getBoundaryLayerGeoJson.bind(this)
    );

    // Renders the selected region on the map.
    this.selectedRegion$.subscribe((selectedRegion: Region | null) => {
      this.displayRegionBoundary(map, selectedRegion);
    });

    this.showConfirmAreaButton$.subscribe((value: boolean) => {
      if (
        !value &&
        this.selectedAreaCreationAction === AreaCreationAction.UPLOAD
      ) {
        const selectedMapIndex =
          this.mapViewOptions$.getValue().selectedMapIndex;
        this.mapManager.removeDrawingControl(
          this.maps[selectedMapIndex].instance!
        );
        this.showUploader = true;
      }
    });

    // Mark the map as selected when the user clicks anywhere on it.
    map.instance?.addEventListener('click', () => {
      this.selectMap(this.maps.indexOf(map));
    });

    // Initialize the legend with colormap values.
    this.updateLegendWithColormap(map, map.config.dataLayerConfig.colormap);

    // Calculate the maximum width of the map nameplate.
    this.updateMapNameplateWidth(map);
  }

  private updateMapNameplateWidth(map: Map) {
    this.mapNameplateWidths[this.maps.indexOf(map)].next(
      this.getMapNameplateWidth(map)
    );
  }

  private getMapNameplateWidth(map: Map): number | null {
    const mapElement = document.getElementById(map.id);
    const attribution = mapElement
      ?.getElementsByClassName('leaflet-control-attribution')
      ?.item(0);
    const mapWidth = !!mapElement ? mapElement.clientWidth : null;
    const attributionWidth = !!attribution ? attribution.clientWidth : null;
    // The maximum width of the nameplate is equal to the width of the map minus the width
    // of Leaflet's attribution control. Additional padding/margins may be applied in the
    // nameplate component, but are not considered for this width.
    const nameplateWidth =
      !!mapWidth && !!attributionWidth ? mapWidth - attributionWidth : null;
    return nameplateWidth;
  }

  private startLoadingLayerCallback(layerName: string) {
    this.loadingIndicators[layerName] = true;
  }
  private doneLoadingLayerCallback(layerName: string) {
    this.loadingIndicators[layerName] = false;
  }

  private createDetailCardCallback(
    features: Feature<Geometry, any>[],
    onInitialized: () => void
  ): any {
    let component = createComponent(ProjectCardComponent, {
      environmentInjector: this.environmentInjector,
    });
    component.instance.initializedEvent.subscribe((_) => onInitialized());
    component.instance.features = features;
    this.applicationRef.attachView(component.hostView);
    return component.location.nativeElement;
  }

  private getBoundaryLayerGeoJson(
    boundaryName: string
  ): Observable<GeoJSON.GeoJSON> {
    return this.selectedRegion$.pipe(
      switchMap((region) =>
        this.mapService.getBoundaryShapes(boundaryName, region)
      )
    );
  }

  /** Configures and opens the Create Plan dialog */
  openCreatePlanDialog() {
    const dialogConfig = new MatDialogConfig();
    dialogConfig.maxWidth = '560px';

    const openedDialog = this.dialog.open(
      PlanCreateDialogComponent,
      dialogConfig
    );

    openedDialog.afterClosed().subscribe((result) => {
      if (result) {
        this.createPlan(result.value, this.mapManager.convertToPlanningArea());
      }
    });
  }

  private createPlan(name: string, shape: GeoJSON.GeoJSON) {
    this.selectedRegion$.subscribe((selectedRegion) => {
      if (!selectedRegion) {
        this.matSnackBar.open('[Error] Please select a region!', 'Dismiss', {
          duration: 10000,
          panelClass: ['snackbar-error'],
          verticalPosition: 'top',
        });
        return;
      }

      this.planService
        .createPlan({
          name: name,
          ownerId: 'tempUserId',
          region: selectedRegion,
          planningArea: shape,
        })
        .subscribe({
          next: (result) => {
            this.router.navigate(['plan', result.result!.id]);
          },
          error: (e) => {
            this.matSnackBar.open('[Error] Unable to create plan due to backend error.', 'Dismiss', {
              duration: 10000,
              panelClass: ['snackbar-error'],
              verticalPosition: 'top',
            });
          },
        });
    });
  }

  /** Handles the area creation action change. */
  onAreaCreationActionChange(option: AreaCreationAction) {
    const selectedMapIndex = this.mapViewOptions$.getValue().selectedMapIndex;
    this.selectedAreaCreationAction = option;
    if (option === AreaCreationAction.DRAW) {
      this.addDrawingControlToAllMaps();
      this.mapManager.enablePolygonDrawingTool(
        this.maps[selectedMapIndex].instance!
      );
      this.showUploader = false;
      this.changeMapCount(1);
    }
    if (option === AreaCreationAction.UPLOAD) {
      if (!this.showConfirmAreaButton$.value) {
        this.maps[selectedMapIndex].instance!.pm.removeControls();
      }
      this.mapManager.disablePolygonDrawingTool(
        this.maps[selectedMapIndex].instance!
      );
      this.showUploader = !this.showUploader;
    }
  }

  cancelAreaCreationAction() {
    const selectedMapIndex = this.mapViewOptions$.getValue().selectedMapIndex;
    this.mapManager.removeDrawingControl(this.maps[selectedMapIndex].instance!);
    this.mapManager.disablePolygonDrawingTool(
      this.maps[selectedMapIndex].instance!
    );
    this.mapManager.clearAllDrawings();
    this.selectedAreaCreationAction = AreaCreationAction.NONE;
    this.showUploader = false;
  }

  private addDrawingControlToAllMaps() {
    this.maps.forEach((map: Map) => {
      const selectedMapIndex = this.mapViewOptions$.getValue().selectedMapIndex;
      // Only add drawing controls to the selected map
      if (selectedMapIndex === this.maps.indexOf(map)) {
        this.mapManager.addDrawingControl(
          this.maps[selectedMapIndex].instance!
        );
      } else {
        // Show a copy of the drawing layer on the other maps
        this.mapManager.showClonedDrawing(map);
      }
    });
  }

  /** Converts and adds the editable shapefile to the map. */
  async loadArea(event: { type: string; value: File }) {
    const file = event.value;
    if (file) {
      const reader = new FileReader();
      const fileAsArrayBuffer: ArrayBuffer = await new Promise((resolve) => {
        reader.onload = () => {
          resolve(reader.result as ArrayBuffer);
        };
        reader.readAsArrayBuffer(file);
      });
      try {
        const geojson = (await shp.parseZip(
          fileAsArrayBuffer
        )) as GeoJSON.GeoJSON;
        if (geojson.type == 'FeatureCollection') {
          this.mapManager.addGeoJsonToDrawing(geojson);
          this.showUploader = false;
          this.addDrawingControlToAllMaps();
        } else {
          this.showUploadError();
        }
      } catch (e) {
        this.showUploadError();
      }
    }
  }

  private showUploadError() {
    this.matSnackBar.open('[Error] Not a valid shapefile!', 'Dismiss', {
      duration: 10000,
      panelClass: ['snackbar-error'],
      verticalPosition: 'top',
    });
  }

  /** Gets the selected region geojson and renders it on the map. */
  private displayRegionBoundary(map: Map, selectedRegion: Region | null) {
    if (!selectedRegion) return;
    if (!map.instance) return;
    this.mapService
      .getRegionBoundary(selectedRegion)
      .subscribe((boundary: GeoJSON.GeoJSON) => {
        this.mapManager.maskOutsideRegion(map.instance!, boundary);
      });
  }

  /** Toggles which base layer is shown. */
  changeBaseLayer(map: Map) {
    this.mapManager.changeBaseLayer(map);

    // Changing the base layer may change the attribution, so the map nameplate
    // width should be recalculated.
    this.updateMapNameplateWidth(map);
  }

  /** Toggles which boundary layer is shown. */
  toggleBoundaryLayer(map: Map) {
    this.mapManager.toggleBoundaryLayer(
      map,
      this.getBoundaryLayerGeoJson.bind(this)
    );
  }

  /** Toggles whether existing projects from CalMapper are shown. */
  toggleExistingProjectsLayer(map: Map) {
    this.mapManager.toggleExistingProjectsLayer(map);
  }

  /** Changes which condition scores layer (if any) is shown. */
  changeConditionsLayer(map: Map) {
    this.mapManager.changeConditionsLayer(map);
    this.updateLegendWithColormap(map, map.config.dataLayerConfig.colormap);
  }

  private updateLegendWithColormap(map: Map, colormap?: string) {
    if (colormap == undefined) {
      colormap = DEFAULT_COLORMAP;
    } else if (colormap == NONE_COLORMAP) {
      map.legend = undefined;
      return;
    }

    this.mapService
      .getColormap(colormap)
      .pipe(take(1))
      .subscribe((colormapConfig) => {
        map.legend = colormapConfigToLegend(colormapConfig);
      });
  }

  /** Change how many maps are displayed in the viewport. */
  changeMapCount(mapCount: number) {
    const mapViewOptions = this.mapViewOptions$.getValue();
    mapViewOptions.numVisibleMaps = mapCount;
    this.mapViewOptions$.next(mapViewOptions);
    setTimeout(() => {
      this.maps.forEach((map: Map) => {
        map.instance?.invalidateSize();
        // Recalculate the map nameplate size.
        this.updateMapNameplateWidth(map);
      });
    }, 0);
  }

  /** Select a map and update which map contains the drawing layer. */
  selectMap(mapIndex: number) {
    const mapViewOptions = this.mapViewOptions$.getValue();
    const previousMapIndex = mapViewOptions.selectedMapIndex;

    if (previousMapIndex !== mapIndex) {
      mapViewOptions.selectedMapIndex = mapIndex;
      this.mapViewOptions$.next(mapViewOptions);
      this.sessionService.setMapViewOptions(mapViewOptions);

      // Toggle the cloned layer on if the map is not the current selected map.
      // Toggle on the drawing layer and control on the selected map.
      if (
        this.selectedAreaCreationAction === AreaCreationAction.DRAW ||
        this.showConfirmAreaButton$.value
      ) {
        this.mapManager.disablePolygonDrawingTool(
          this.maps[previousMapIndex].instance!
        );
        this.mapManager.removeDrawingControl(
          this.maps[previousMapIndex].instance!
        );
        this.mapManager.showClonedDrawing(this.maps[previousMapIndex]);
        this.mapManager.addDrawingControl(this.maps[mapIndex].instance!);
        this.mapManager.hideClonedDrawing(this.maps[mapIndex]);
      }
    }
  }

  /**
   * Whether the map at given index should be visible.
   *
   *  WARNING: This function is run constantly and shouldn't do any heavy lifting!
   */
  isMapVisible(index: number): boolean {
    if (index === this.mapViewOptions$.getValue().selectedMapIndex) return true;

    switch (this.mapViewOptions$.getValue().numVisibleMaps) {
      case 4:
        return true;
      case 1:
        // Only 1 map is visible and this one is not selected
        return false;
      case 2:
      default:
        // In 2 map view, if the 1st or 2nd map are selected, show maps 1 and 2
        // Otherwise, show maps 3 and 4
        // TODO: 2 map view might go away or the logic here might change
        return (
          Math.floor(this.mapViewOptions$.getValue().selectedMapIndex / 2) ===
          Math.floor(index / 2)
        );
    }
  }

  /** Computes the height for the map row at given index (0%, 50%, or 100%).
   *
   *  WARNING: This function is run constantly and shouldn't do any heavy lifting!
   */
  mapRowHeight(index: number): string {
    switch (this.mapViewOptions$.getValue().numVisibleMaps) {
      case 4:
        return '50%';
      case 2:
      case 1:
      default:
        if (
          Math.floor(this.mapViewOptions$.getValue().selectedMapIndex / 2) ===
          index
        ) {
          return '100%';
        }
        return '0%';
    }
  }

  /** Gets the legend that should be shown in the sidebar.
   *
   *  WARNING: This function is run constantly and shouldn't do any heavy lifting!
   */
  getSelectedLegend(): Legend | undefined {
    return this.maps[this.mapViewOptions$.getValue().selectedMapIndex].legend;
  }

  /** Used to compute whether a node in the condition layer tree has children. */
  hasChild = (_: number, node: ConditionsNode) =>
    !!node.children && node.children.length > 0;

  /** Used to compute whether to show the info button on a condition layer node. */
  showInfoIcon = (node: ConditionsNode) =>
    node.filepath?.length && (node.showInfoIcon || node.infoMenuOpen);

  /** Unstyles all nodes in the tree using recursion. */
  unstyleAllNodes(node?: ConditionsNode): void {
    if (!node && this.conditionDataSource.data.length > 0) {
      this.conditionDataSource.data.forEach((node) =>
        this.unstyleAllNodes(node)
      );
    } else if (node) {
      node.styleDisabled = false;
      node.children?.forEach((child) => this.unstyleAllNodes(child));
    }
  }

  /** Visually indicates that all the descendants of a condition layer node are
   *  included in the current analysis by setting their style, using recursion.
   */
  styleDescendantsDisabled(node: ConditionsNode): void {
    node.children?.forEach((child) => {
      child.styleDisabled = true;
      this.styleDescendantsDisabled(child);
    });
  }

  onSelect(node: ConditionsNode): void {
    this.unstyleAllNodes();
    this.styleDescendantsDisabled(node);
  }

  private conditionsConfigToData(config: ConditionsConfig): ConditionsNode[] {
    return [
      NONE_DATA_LAYER_CONFIG,
      {
        ...config,
        display_name: 'Current condition',
        disableSelect: true,
        children: config.pillars
          ?.filter((pillar) => pillar.display)
          .map((pillar): ConditionsNode => {
            return {
              ...pillar,
              disableSelect: true,
              children: pillar.elements?.map((element): ConditionsNode => {
                return {
                  ...element,
                  disableSelect: true,
                  children: element.metrics,
                };
              }),
            };
          }),
      },
      {
        display_name: 'Current condition (normalized)',
        filepath: config.filepath?.concat('_normalized'),
        colormap: config.colormap,
        normalized: true,
        disableSelect: true,
        children: config.pillars
          ?.filter((pillar) => pillar.display)
          .map((pillar): ConditionsNode => {
            return {
              ...pillar,
              filepath: pillar.filepath?.concat('_normalized'),
              normalized: true,
              children: pillar.elements?.map((element): ConditionsNode => {
                return {
                  ...element,
                  filepath: element.filepath?.concat('_normalized'),
                  normalized: true,
                  children: element.metrics?.map((metric): ConditionsNode => {
                    return {
                      ...metric,
                      filepath: metric.filepath?.concat('_normalized'),
                      normalized: true,
                    };
                  }),
                };
              }),
            };
          }),
      },
    ];
  }

  /** Find the node matching the given filepath in the condition tree (if any), and expand its ancestors
   *  so it becomes visible.
   */
  private findAndRevealNodeWithFilepath(
    filepath: string | undefined
  ): ConditionsNode {
    if (!filepath || filepath === NONE_DATA_LAYER_CONFIG.filepath)
      return NONE_DATA_LAYER_CONFIG;
    for (let tree of this.conditionDataSource.data) {
      if (tree.filepath === filepath) return tree;
      if (tree.children) {
        for (let pillar of tree.children) {
          if (pillar.filepath === filepath) {
            this.conditionTreeControl.expand(tree);
            return pillar;
          }
          if (pillar.children) {
            for (let element of pillar.children) {
              if (element.filepath === filepath) {
                this.conditionTreeControl.expand(tree);
                this.conditionTreeControl.expand(pillar);
                return element;
              }
              if (element.children) {
                for (let metric of element.children) {
                  if (metric.filepath === filepath) {
                    this.conditionTreeControl.expand(tree);
                    this.conditionTreeControl.expand(pillar);
                    this.conditionTreeControl.expand(element);
                    return metric;
                  }
                }
              }
            }
          }
        }
      }
    }
    return NONE_DATA_LAYER_CONFIG;
  }
}
