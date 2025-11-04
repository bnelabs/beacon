# Frontend E2E Test Scenarios

This document outlines comprehensive end-to-end test scenarios for the BEACON frontend. These tests should be implemented using Cypress or Playwright.

## Test Setup

```javascript
// cypress/e2e/beacon.cy.js or tests/e2e/beacon.spec.js

describe('BEACON Platform E2E Tests', () => {
  const BASE_URL = 'http://localhost:9876'
  const API_URL = 'http://localhost:3456'

  beforeEach(() => {
    // Intercept API calls for faster, more reliable tests
    cy.intercept('GET', `${API_URL}/api/v1/jobs*`).as('getJobs')
    cy.intercept('GET', `${API_URL}/api/v1/data-sources*`).as('getDataSources')
    cy.intercept('GET', `${API_URL}/api/v1/catalogue*`).as('getCatalogue')
    cy.visit(BASE_URL)
  })
})
```

---

## Test Suite 1: Navigation & Routing

### Test 1.1: Initial Page Load
```javascript
it('should load dashboard on initial visit', () => {
  cy.visit(BASE_URL)
  cy.contains('Dashboard')
  cy.url().should('eq', BASE_URL + '/')
})
```

### Test 1.2: Sidebar Navigation
```javascript
it('should navigate between all pages', () => {
  const pages = [
    { name: 'Dashboard', url: '/' },
    { name: 'Globe View', url: '/globe' },
    { name: 'Data Sources', url: '/datasources' },
    { name: 'Jobs', url: '/jobs' },
    { name: 'Models', url: '/models' },
    { name: 'Results', url: '/results' },
    { name: 'Settings', url: '/settings' },
    { name: 'Help', url: '/help' }
  ]

  pages.forEach(page => {
    cy.contains(page.name).click()
    cy.url().should('include', page.url)
    cy.contains(page.name) // Page title
  })
})
```

### Test 1.3: Active Navigation State
```javascript
it('should highlight active navigation item', () => {
  cy.contains('Data Sources').click()
  cy.get('nav').contains('Data Sources')
    .parent()
    .should('have.class', 'active') // or whatever class indicates active state
})
```

---

## Test Suite 2: Dashboard Functionality

### Test 2.1: Stats Display
```javascript
it('should display dashboard statistics', () => {
  cy.visit(BASE_URL)
  cy.wait('@getJobs')

  // Check all stat cards
  cy.contains('Total Jobs')
  cy.contains('Active Models')
  cy.contains('Data Sources')
  cy.contains('Completion Rate')

  // Verify numeric values
  cy.get('[data-testid="total-jobs-stat"]').should('contain', /\d+/)
})
```

### Test 2.2: Recent Jobs List
```javascript
it('should show recent jobs with status badges', () => {
  cy.visit(BASE_URL)
  cy.wait('@getJobs')

  cy.get('[data-testid="recent-jobs"]').within(() => {
    // Should show up to 5 recent jobs
    cy.get('[data-testid="job-item"]').should('have.length.at.most', 5)

    // Each job should have status badge
    cy.get('[data-testid="job-item"]').each(($job) => {
      cy.wrap($job).find('[data-testid="status-badge"]').should('exist')
    })
  })
})
```

### Test 2.3: New Job Button
```javascript
it('should open job creation modal from dashboard', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()
  cy.get('[data-testid="job-creation-modal"]').should('be.visible')
  cy.contains('Create New Job')
})
```

---

## Test Suite 3: Data Sources Management

### Test 3.1: Data Sources List
```javascript
it('should display all data sources', () => {
  cy.visit(BASE_URL + '/datasources')
  cy.wait('@getDataSources')

  cy.get('[data-testid="data-source-card"]').should('have.length.at.least', 1)

  // Check card content
  cy.get('[data-testid="data-source-card"]').first().within(() => {
    cy.get('[data-testid="source-name"]').should('be.visible')
    cy.get('[data-testid="source-status"]').should('be.visible')
    cy.contains('button', 'Sync Now')
    cy.contains('button', 'Configure')
    cy.contains('button', 'View Data')
  })
})
```

### Test 3.2: Workflow Guide Visibility
```javascript
it('should show workflow guide', () => {
  cy.visit(BASE_URL + '/datasources')

  cy.contains('How to prepare data for Beacon')
  cy.contains('Locate data by region')
  cy.contains('Review data health')
  cy.contains('Launch collection job')
  cy.contains('Train and simulate')
})
```

### Test 3.3: Add New Data Source
```javascript
it('should open form modal to add data source', () => {
  cy.visit(BASE_URL + '/datasources')
  cy.contains('button', 'Add Source').click()

  cy.get('[data-testid="data-source-form-modal"]').should('be.visible')
  cy.contains('Create Data Source') // or similar title

  // Check form fields
  cy.get('input[name="name"]').should('be.visible')
  cy.get('select[name="plugin_type"]').should('be.visible')
  cy.get('textarea[name="description"]').should('be.visible')
})
```

### Test 3.4: View Data Source Details
```javascript
it('should open details modal when viewing data', () => {
  cy.visit(BASE_URL + '/datasources')
  cy.wait('@getDataSources')

  cy.get('[data-testid="data-source-card"]').first().within(() => {
    cy.contains('button', 'View Data').click()
  })

  cy.get('[data-testid="data-source-details-modal"]').should('be.visible')
  cy.wait('@getCatalogue')
})
```

### Test 3.5: Sync Data Source
```javascript
it('should show loading state when syncing', () => {
  cy.intercept('POST', `${API_URL}/api/v1/data-sources/*/sync`).as('syncSource')

  cy.visit(BASE_URL + '/datasources')
  cy.wait('@getDataSources')

  cy.get('[data-testid="data-source-card"]').first().within(() => {
    cy.contains('button', 'Sync Now').click()
  })

  // Should show loading state
  cy.get('[data-testid="sync-button"]').should('contain', 'loading')

  cy.wait('@syncSource')
})
```

---

## Test Suite 4: Job Creation Workflow

### Test 4.1: Open Job Modal and Select Type
```javascript
it('should allow selecting job type', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()

  cy.get('select[name="jobType"]').select('data_collection')
  cy.contains('Download and prepare data from the configured catalogue')

  cy.get('select[name="jobType"]').select('training')
  cy.contains('Train an AI model using a completed data collection job')
})
```

### Test 4.2: Data Collection Job - Basic Fields
```javascript
it('should create data collection job with basic parameters', () => {
  cy.intercept('POST', `${API_URL}/api/v1/jobs`).as('createJob')

  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()

  // Fill in basic fields
  cy.get('input[name="name"]').type('Test Data Collection')
  cy.get('textarea[name="description"]').type('E2E test job')
  cy.get('select[name="jobType"]').select('data_collection')

  // Select region
  cy.get('select[name="region"]').select('NORTH_AMERICA')

  // Set date range
  cy.get('input[name="startDate"]').type('2023-01-01')
  cy.get('input[name="endDate"]').type('2023-12-31')

  // Submit
  cy.contains('button', 'Create Job').click()

  cy.wait('@createJob')

  // Modal should close
  cy.get('[data-testid="job-creation-modal"]').should('not.exist')
})
```

### Test 4.3: Dataset Selection in Job Creation
```javascript
it('should allow selecting specific datasets', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()
  cy.wait('@getCatalogue')

  cy.get('select[name="jobType"]').select('data_collection')

  // Search for dataset
  cy.get('input[placeholder*="Filter"]').type('stock')

  // Select first matching dataset
  cy.get('[data-testid="catalogue-item"]').first().within(() => {
    cy.get('input[type="checkbox"]').check()
  })

  // Verify it appears in selected list
  cy.get('[data-testid="selected-datasets"]').should('contain', '1')

  // Select all shown
  cy.contains('button', 'Select all shown').click()
  cy.get('[data-testid="selected-datasets"]').should('contain', /\d+/)

  // Clear all
  cy.contains('button', 'Clear shown').click()
})
```

### Test 4.4: Training Job - Model Configuration
```javascript
it('should configure training job parameters', () => {
  cy.intercept('GET', `${API_URL}/api/v1/jobs*`).as('getJobs')

  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()
  cy.wait('@getJobs')

  cy.get('select[name="jobType"]').select('training')

  // Select data job
  cy.get('select[name="dataJobId"]').select(1) // Select first completed job

  // Select model type
  cy.get('select[name="modelType"]').select('temporal_attention')

  // Configure hyperparameters
  cy.get('input[name="epochs"]').clear().type('10')
  cy.get('input[name="sequenceLength"]').clear().type('20')
  cy.get('input[name="batchSize"]').clear().type('16')
  cy.get('input[name="learningRate"]').clear().type('0.001')
  cy.get('input[name="dropout"]').clear().type('0.2')

  // Set date ranges
  cy.get('input[name="trainStart"]').type('2023-01-01')
  cy.get('input[name="trainEnd"]').type('2023-06-30')
  cy.get('input[name="testStart"]').type('2023-07-01')
  cy.get('input[name="testEnd"]').type('2023-12-31')

  // Verify form is filled
  cy.get('input[name="epochs"]').should('have.value', '10')
})
```

### Test 4.5: Form Validation
```javascript
it('should show validation error for training without data job', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()

  cy.get('select[name="jobType"]').select('training')

  // Try to submit without selecting data job
  cy.contains('button', 'Create Job').click()

  // Should show error
  cy.contains('Select a completed data collection job')
})
```

---

## Test Suite 5: Data Catalogue Filtering

### Test 5.1: Filter by Search Term
```javascript
it('should filter catalogue items by search term', () => {
  cy.visit(BASE_URL + '/datasources')
  cy.get('[data-testid="data-source-card"]').first().within(() => {
    cy.contains('button', 'View Data').click()
  })
  cy.wait('@getCatalogue')

  const searchTerm = 'stock'
  cy.get('input[placeholder*="Filter"]').type(searchTerm)

  // All visible items should contain search term
  cy.get('[data-testid="catalogue-item"]').each(($item) => {
    cy.wrap($item).should('contain.text', new RegExp(searchTerm, 'i'))
  })
})
```

### Test 5.2: Filter by Region
```javascript
it('should filter catalogue by region', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()
  cy.wait('@getCatalogue')

  cy.get('select[name="region"]').select('EUROPE')

  // Should filter catalogue to European datasets
  cy.wait('@getCatalogue')

  // Verify filtered results
  cy.get('[data-testid="catalogue-item"]').each(($item) => {
    cy.wrap($item).should('contain', 'europe')
  })
})
```

### Test 5.3: Group by Data Source
```javascript
it('should display catalogue items grouped by data source', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()
  cy.wait('@getCatalogue')

  // Should have group headers
  cy.get('[data-testid="catalogue-group-header"]').should('have.length.at.least', 1)

  // Each group should have items
  cy.get('[data-testid="catalogue-group"]').each(($group) => {
    cy.wrap($group).find('[data-testid="catalogue-item"]').should('have.length.at.least', 1)
  })
})
```

---

## Test Suite 6: Models & Results

### Test 6.1: Models Page Display
```javascript
it('should display trained models', () => {
  cy.visit(BASE_URL + '/models')

  // Should show models or empty state
  cy.get('body').then($body => {
    if ($body.find('[data-testid="model-card"]').length > 0) {
      cy.get('[data-testid="model-card"]').should('be.visible')
      cy.get('[data-testid="model-card"]').first().within(() => {
        cy.get('[data-testid="model-name"]').should('be.visible')
        cy.get('[data-testid="model-metrics"]').should('be.visible')
      })
    } else {
      cy.contains('No models available')
    }
  })
})
```

### Test 6.2: Results Page Navigation
```javascript
it('should navigate to results page', () => {
  cy.visit(BASE_URL + '/results')
  cy.contains('Results')

  // Should show results or empty state
  cy.get('body').should('be.visible')
})
```

---

## Test Suite 7: Loading States & Error Handling

### Test 7.1: Loading Spinners
```javascript
it('should show loading spinner while fetching data', () => {
  cy.intercept('GET', `${API_URL}/api/v1/jobs*`, (req) => {
    req.reply((res) => {
      res.delay = 1000 // Add delay to see spinner
    })
  }).as('slowJobs')

  cy.visit(BASE_URL)

  cy.get('[data-testid="loading-spinner"]').should('be.visible')
  cy.wait('@slowJobs')
  cy.get('[data-testid="loading-spinner"]').should('not.exist')
})
```

### Test 7.2: Error Message Display
```javascript
it('should show error message on API failure', () => {
  cy.intercept('GET', `${API_URL}/api/v1/jobs*`, {
    statusCode: 500,
    body: { detail: 'Internal server error' }
  }).as('failedJobs')

  cy.visit(BASE_URL)
  cy.wait('@failedJobs')

  cy.get('[data-testid="error-message"]').should('be.visible')
  cy.contains(/error/i)
})
```

### Test 7.3: Retry Failed Requests
```javascript
it('should allow retrying failed requests', () => {
  cy.intercept('GET', `${API_URL}/api/v1/jobs*`, {
    statusCode: 500
  }).as('failedJobs')

  cy.visit(BASE_URL)
  cy.wait('@failedJobs')

  cy.get('[data-testid="error-message"]').should('be.visible')

  // Setup successful response for retry
  cy.intercept('GET', `${API_URL}/api/v1/jobs*`, {
    statusCode: 200,
    body: []
  }).as('successJobs')

  cy.contains('button', /retry/i).click()
  cy.wait('@successJobs')

  cy.get('[data-testid="error-message"]').should('not.exist')
})
```

---

## Test Suite 8: Globe View

### Test 8.1: Globe Rendering
```javascript
it('should render 3D globe', () => {
  cy.visit(BASE_URL + '/globe')

  // Check for canvas element (Three.js renders to canvas)
  cy.get('canvas').should('be.visible')

  // Should show loading initially, then globe
  cy.contains('Globe View')
})
```

### Test 8.2: Globe Interactions
```javascript
it('should allow interacting with globe', () => {
  cy.visit(BASE_URL + '/globe')
  cy.wait(2000) // Wait for globe to render

  // Get canvas
  cy.get('canvas').then($canvas => {
    const canvas = $canvas[0]

    // Simulate mouse drag to rotate
    cy.wrap(canvas)
      .trigger('mousedown', { clientX: 100, clientY: 100 })
      .trigger('mousemove', { clientX: 200, clientY: 200 })
      .trigger('mouseup')
  })
})
```

---

## Test Suite 9: Responsive Design

### Test 9.1: Mobile Viewport
```javascript
it('should work on mobile viewport', () => {
  cy.viewport('iphone-x')
  cy.visit(BASE_URL)

  // Should show mobile navigation
  cy.get('[data-testid="mobile-menu-button"]').should('be.visible')

  // Open menu
  cy.get('[data-testid="mobile-menu-button"]').click()
  cy.get('[data-testid="mobile-menu"]').should('be.visible')
})
```

### Test 9.2: Tablet Viewport
```javascript
it('should work on tablet viewport', () => {
  cy.viewport('ipad-2')
  cy.visit(BASE_URL)

  // Check layout adjustments
  cy.get('[data-testid="stat-card"]').should('be.visible')
})
```

### Test 9.3: Desktop Viewport
```javascript
it('should work on desktop viewport', () => {
  cy.viewport(1920, 1080)
  cy.visit(BASE_URL)

  // Sidebar should be visible
  cy.get('[data-testid="sidebar"]').should('be.visible')
})
```

---

## Test Suite 10: Accessibility

### Test 10.1: Keyboard Navigation
```javascript
it('should support keyboard navigation', () => {
  cy.visit(BASE_URL)

  // Tab through interactive elements
  cy.get('body').tab()
  cy.focused().should('have.attr', 'href') // First link/button

  cy.focused().tab()
  cy.focused().should('be.visible')
})
```

### Test 10.2: Focus Indicators
```javascript
it('should show focus indicators on interactive elements', () => {
  cy.visit(BASE_URL)

  cy.get('button').first().focus()
  cy.focused().should('have.css', 'outline').and('not.equal', 'none')
})
```

---

## Test Suite 11: State Persistence

### Test 11.1: Form State Persistence
```javascript
it('should preserve form state when modal reopens', () => {
  cy.visit(BASE_URL)
  cy.contains('button', 'New Job').click()

  // Fill in some fields
  cy.get('input[name="name"]').type('Test Job')
  cy.get('select[name="region"]').select('EUROPE')

  // Close modal
  cy.contains('button', 'Cancel').click()

  // Reopen modal
  cy.contains('button', 'New Job').click()

  // Form should be reset (based on current implementation)
  cy.get('input[name="name"]').should('have.value', '')
})
```

---

## Test Suite 12: Performance

### Test 12.1: Initial Load Time
```javascript
it('should load in under 3 seconds', () => {
  const startTime = Date.now()

  cy.visit(BASE_URL)
  cy.wait('@getJobs')

  cy.window().then(() => {
    const loadTime = Date.now() - startTime
    expect(loadTime).to.be.lessThan(3000)
  })
})
```

### Test 12.2: Bundle Size
```javascript
it('should have reasonable bundle size', () => {
  cy.visit(BASE_URL)

  cy.window().then(win => {
    const resources = win.performance.getEntriesByType('resource')
    const jsFiles = resources.filter(r => r.name.includes('.js'))

    jsFiles.forEach(file => {
      // Each JS file should be under 500KB
      expect(file.transferSize).to.be.lessThan(500 * 1024)
    })
  })
})
```

---

## Implementation Guide

### Setting up Cypress

```bash
cd frontend
npm install --save-dev cypress

# Add to package.json scripts:
{
  "scripts": {
    "test:e2e": "cypress open",
    "test:e2e:headless": "cypress run"
  }
}
```

### Setting up Playwright

```bash
cd frontend
npm install --save-dev @playwright/test

# Add to package.json scripts:
{
  "scripts": {
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui"
  }
}
```

### Test Data Management

Create fixtures for consistent test data:

```javascript
// cypress/fixtures/jobs.json
[
  {
    "id": 1,
    "name": "Test Job",
    "status": "completed",
    "job_type": "data_collection"
  }
]

// In test:
cy.intercept('GET', '/api/v1/jobs', { fixture: 'jobs.json' })
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: E2E Tests

on: [push, pull_request]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'

      - name: Start services
        run: docker compose up -d

      - name: Wait for services
        run: |
          timeout 60 bash -c 'until curl -f http://localhost:9876/health; do sleep 2; done'

      - name: Install dependencies
        run: |
          cd frontend
          npm ci

      - name: Run E2E tests
        run: |
          cd frontend
          npm run test:e2e:headless

      - name: Upload screenshots on failure
        if: failure()
        uses: actions/upload-artifact@v3
        with:
          name: cypress-screenshots
          path: frontend/cypress/screenshots
```

---

## Maintenance Notes

1. **Keep tests independent:** Each test should be able to run in isolation
2. **Use data-testid attributes:** Add `data-testid` to important elements for stable selectors
3. **Mock API responses:** Use intercepts for faster, more reliable tests
4. **Clean up after tests:** Reset state between tests
5. **Update tests with features:** Keep tests in sync with feature development

---

## Priority Test Implementation Order

1. **High Priority:**
   - Navigation & Routing
   - Job Creation Workflow
   - Data Sources Management

2. **Medium Priority:**
   - Dashboard Functionality
   - Catalogue Filtering
   - Loading States & Error Handling

3. **Low Priority:**
   - Globe View
   - Responsive Design
   - Accessibility
   - Performance

---

**Total Scenarios:** 40+
**Estimated Implementation Time:** 2-3 days
**Maintenance Overhead:** Low (with proper structure)
