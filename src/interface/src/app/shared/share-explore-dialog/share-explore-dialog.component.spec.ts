import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ShareExploreDialogComponent } from './share-explore-dialog.component';

import { MaterialModule } from '../../material/material.module';
import { MockProvider } from 'ng-mocks';
import { MatDialogRef } from '@angular/material/dialog';
import { ShareMapService } from '../../services/share-map.service';

describe('ShareExploreDialogComponent', () => {
  let component: ShareExploreDialogComponent;
  let fixture: ComponentFixture<ShareExploreDialogComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ShareExploreDialogComponent],
      imports: [MaterialModule],
      providers: [MockProvider(MatDialogRef), MockProvider(ShareMapService)],
    }).compileComponents();

    fixture = TestBed.createComponent(ShareExploreDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
