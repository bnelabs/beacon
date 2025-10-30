import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Container, Grid, Typography, Fade } from '@mui/material';
import { bneColors, bneGradients } from '../theme/bneTheme';
import GlobeVisualization from '../components/Globe/GlobeVisualization';
import RegionSelector from '../components/Globe/RegionSelector';
import DataSourceSelector from '../components/Globe/DataSourceSelector';

export default function DataCatalogueSelector() {
  const navigate = useNavigate();
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [hoveredRegion, setHoveredRegion] = useState<string | null>(null);
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [selectedSources, setSelectedSources] = useState<number[]>([]);

  const handleRegionSelect = (regionId: string | null) => {
    setSelectedRegion(regionId);
    setSelectedCountries([]); // Reset country selection when region changes
  };

  const handleClearSelection = () => {
    setSelectedRegion(null);
    setSelectedCountries([]);
    setSelectedSources([]);
  };

  const handleProceed = () => {
    // Navigate to catalogue with selected filters
    const params = new URLSearchParams();
    if (selectedRegion) {
      params.append('region', selectedRegion);
    }
    if (selectedCountries.length > 0) {
      params.append('countries', selectedCountries.join(','));
    }
    if (selectedSources.length > 0) {
      params.append('sources', selectedSources.join(','));
    }
    navigate(`/catalogue?${params.toString()}`);
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        background: bneGradients.dark,
        py: 4,
      }}
    >
      <Container maxWidth="xl">
        {/* Header */}
        <Fade in timeout={800}>
          <Box sx={{ mb: 4, textAlign: 'center' }}>
            <Typography
              variant="h3"
              sx={{
                color: bneColors.neutral[50],
                fontWeight: 700,
                mb: 1,
                background: bneGradients.premium,
                backgroundClip: 'text',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}
            >
              BEACON Data Catalogue
            </Typography>
            <Typography
              variant="h6"
              sx={{
                color: bneColors.neutral[400],
                fontWeight: 400,
              }}
            >
              Banking Early Alert Comprehensive Observation Network
            </Typography>
            <Typography
              variant="body2"
              sx={{
                color: bneColors.neutral[500],
                mt: 1,
              }}
            >
              Select geographic regions and data sources to build your financial dataset
            </Typography>
          </Box>
        </Fade>

        {/* Main Content Grid */}
        <Grid container spacing={3}>
          {/* Left Panel - Region & Source Selection */}
          <Grid item xs={12} lg={3}>
            <Fade in timeout={1000}>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <RegionSelector
                  selectedRegion={selectedRegion}
                  selectedCountries={selectedCountries}
                  onRegionChange={handleRegionSelect}
                  onCountriesChange={setSelectedCountries}
                  onClearSelection={handleClearSelection}
                />
              </Box>
            </Fade>
          </Grid>

          {/* Center - Globe Visualization */}
          <Grid item xs={12} lg={6}>
            <Fade in timeout={1200}>
              <Box>
                <GlobeVisualization
                  selectedRegion={selectedRegion}
                  onRegionSelect={handleRegionSelect}
                  hoveredRegion={hoveredRegion}
                  onRegionHover={setHoveredRegion}
                />

                {/* Info Cards Below Globe */}
                <Grid container spacing={2} sx={{ mt: 2 }}>
                  <Grid item xs={12} sm={4}>
                    <Box
                      sx={{
                        bgcolor: 'rgba(15, 23, 42, 0.8)',
                        backdropFilter: 'blur(10px)',
                        border: `1px solid ${bneColors.neutral[700]}`,
                        borderRadius: 2,
                        p: 2,
                        textAlign: 'center',
                      }}
                    >
                      <Typography
                        variant="h4"
                        sx={{
                          color: bneColors.primary[400],
                          fontWeight: 700,
                          mb: 0.5,
                        }}
                      >
                        75+
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: bneColors.neutral[400] }}
                      >
                        Data Items
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Box
                      sx={{
                        bgcolor: 'rgba(15, 23, 42, 0.8)',
                        backdropFilter: 'blur(10px)',
                        border: `1px solid ${bneColors.neutral[700]}`,
                        borderRadius: 2,
                        p: 2,
                        textAlign: 'center',
                      }}
                    >
                      <Typography
                        variant="h4"
                        sx={{
                          color: bneColors.secondary[500],
                          fontWeight: 700,
                          mb: 0.5,
                        }}
                      >
                        7
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: bneColors.neutral[400] }}
                      >
                        Global Regions
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Box
                      sx={{
                        bgcolor: 'rgba(15, 23, 42, 0.8)',
                        backdropFilter: 'blur(10px)',
                        border: `1px solid ${bneColors.neutral[700]}`,
                        borderRadius: 2,
                        p: 2,
                        textAlign: 'center',
                      }}
                    >
                      <Typography
                        variant="h4"
                        sx={{
                          color: bneColors.accent[500],
                          fontWeight: 700,
                          mb: 0.5,
                        }}
                      >
                        230+
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: bneColors.neutral[400] }}
                      >
                        Countries
                      </Typography>
                    </Box>
                  </Grid>
                </Grid>
              </Box>
            </Fade>
          </Grid>

          {/* Right Panel - Data Source Selection */}
          <Grid item xs={12} lg={3}>
            <Fade in timeout={1400}>
              <Box>
                <DataSourceSelector
                  selectedRegion={selectedRegion}
                  selectedCountries={selectedCountries}
                  selectedSources={selectedSources}
                  onSourcesChange={setSelectedSources}
                  onProceed={handleProceed}
                />
              </Box>
            </Fade>
          </Grid>
        </Grid>

        {/* Footer Info */}
        <Fade in timeout={1600}>
          <Box
            sx={{
              mt: 4,
              p: 3,
              bgcolor: 'rgba(15, 23, 42, 0.6)',
              backdropFilter: 'blur(10px)',
              border: `1px solid ${bneColors.neutral[800]}`,
              borderRadius: 2,
              textAlign: 'center',
            }}
          >
            <Typography variant="body2" sx={{ color: bneColors.neutral[400] }}>
              Powered by <strong style={{ color: bneColors.primary[400] }}>BNE Engine</strong> •
              Real-time liquidity risk analysis with EU AI Act compliance •
              Multi-scale temporal attention models for systemic risk prediction
            </Typography>
          </Box>
        </Fade>
      </Container>
    </Box>
  );
}
