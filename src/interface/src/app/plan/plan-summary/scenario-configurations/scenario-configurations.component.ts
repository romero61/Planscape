import { MatSnackBar } from '@angular/material/snack-bar';
import { Component, Input, OnInit } from '@angular/core';
import { MatCheckboxChange } from '@angular/material/checkbox';
import { PlanService } from 'src/app/services';
import { Plan, ProjectConfig } from 'src/app/types';

interface ProjectConfigRow extends ProjectConfig {
  selected?: boolean;
}

@Component({
  selector: 'app-scenario-configurations',
  templateUrl: './scenario-configurations.component.html',
  styleUrls: ['./scenario-configurations.component.scss'],
})
export class ScenarioConfigurationsComponent implements OnInit {
  @Input() plan: Plan | null = null;
  configurations: ProjectConfigRow[] = [];
  displayedColumns: string[] = [
    'select',
    'createdTimestamp',
    'scoreType',
    'priorities',
    'constraints',
  ];

  constructor(private planService: PlanService, private snackbar: MatSnackBar) {}

  ngOnInit(): void {
    this.fetchProjects();
  }

  fetchProjects(): void {
    this.planService.getProjects(this.plan?.id!).subscribe((result) => {
      this.configurations = result;
    });
  }

  selectAllConfigs(event: MatCheckboxChange): void {
    this.configurations.forEach((config) => (config.selected = event.checked));
  }

  showDeleteButton(): boolean {
    return this.configurations.filter((config) => config.selected).length > 0;
  }

  showContinueButton(): boolean {
    return this.configurations.filter((config) => config.selected).length === 1;
  }

  deleteSelectedConfigs(): void {
    this.planService.deleteProjects(
      this.configurations
        .filter((config) => config.selected)
        .map((config) => config.id)
    ).subscribe((deletedIds) => {
      this.snackbar.open(`Deleted ${deletedIds.length} configuration${deletedIds.length > 1 ? 's' : ''}`);
      this.fetchProjects();
    });
  }
}
