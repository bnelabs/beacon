import React from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Divider,
  Button,
  FormControl,
  FormGroup,
  FormControlLabel,
  Checkbox,
  Collapse,
} from '@mui/material';
import { bneColors } from '../../theme/bneTheme';
import { REGIONS, Region } from '../../data/worldRegions';
import PublicIcon from '@mui/icons-material/Public';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';

interface RegionSelectorProps {
  selectedRegion: string | null;
  selectedCountries: string[];
  onRegionChange: (regionId: string | null) => void;
  onCountriesChange: (countries: string[]) => void;
  onClearSelection: () => void;
}

export default function RegionSelector({
  selectedRegion,
  selectedCountries,
  onRegionChange,
  onCountriesChange,
  onClearSelection,
}: RegionSelectorProps) {
  const region = selectedRegion ? REGIONS[selectedRegion] : null;
  const [showCountries, setShowCountries] = React.useState(false);

  const handleCountryToggle = (countryCode: string) => {
    if (selectedCountries.includes(countryCode)) {
      onCountriesChange(selectedCountries.filter((c) => c !== countryCode));
    } else {
      onCountriesChange([...selectedCountries, countryCode]);
    }
  };

  const handleSelectAllCountries = () => {
    if (region) {
      onCountriesChange(region.countries);
    }
  };

  const handleDeselectAllCountries = () => {
    onCountriesChange([]);
  };

  const isAllSelected = region && selectedCountries.length === region.countries.length;
  const isSomeSelected = selectedCountries.length > 0 && !isAllSelected;

  return (
    <Paper
      elevation={3}
      sx={{
        p: 3,
        bgcolor: 'rgba(15, 23, 42, 0.95)',
        backdropFilter: 'blur(10px)',
        border: `1px solid ${bneColors.neutral[700]}`,
        borderRadius: 3,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <PublicIcon sx={{ color: bneColors.primary[400], fontSize: 28 }} />
        <Typography
          variant="h6"
          sx={{
            color: bneColors.neutral[50],
            fontWeight: 600,
            flex: 1,
          }}
        >
          Region Selection
        </Typography>
      </Box>

      <Divider sx={{ borderColor: bneColors.neutral[700], mb: 3 }} />

      {/* Region Grid */}
      {!selectedRegion ? (
        <>
          <Typography
            variant="body2"
            sx={{ color: bneColors.neutral[400], mb: 2 }}
          >
            Select a geographic region to explore
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: 1.5,
            }}
          >
            {Object.values(REGIONS)
              .filter((r) => r.id !== 'global')
              .map((region) => (
                <Chip
                  key={region.id}
                  label={region.displayName}
                  onClick={() => onRegionChange(region.id)}
                  sx={{
                    bgcolor: `${region.color}20`,
                    color: region.color,
                    border: `1px solid ${region.color}50`,
                    fontWeight: 500,
                    fontSize: '0.875rem',
                    py: 2.5,
                    transition: 'all 0.2s',
                    cursor: 'pointer',
                    '&:hover': {
                      bgcolor: `${region.color}30`,
                      borderColor: region.color,
                      transform: 'translateY(-2px)',
                      boxShadow: `0 4px 12px ${region.color}40`,
                    },
                  }}
                />
              ))}
          </Box>

          {/* Global Option */}
          <Box sx={{ mt: 3 }}>
            <Chip
              label="Global / All Regions"
              onClick={() => onRegionChange('global')}
              sx={{
                width: '100%',
                bgcolor: `${bneColors.neutral[400]}20`,
                color: bneColors.neutral[300],
                border: `1px solid ${bneColors.neutral[600]}`,
                fontWeight: 500,
                py: 2.5,
                transition: 'all 0.2s',
                cursor: 'pointer',
                '&:hover': {
                  bgcolor: `${bneColors.neutral[400]}30`,
                  borderColor: bneColors.neutral[400],
                  transform: 'translateY(-2px)',
                },
              }}
            />
          </Box>
        </>
      ) : (
        <>
          {/* Selected Region */}
          <Box
            sx={{
              bgcolor: `${region?.color}15`,
              border: `2px solid ${region?.color}`,
              borderRadius: 2,
              p: 2,
              mb: 3,
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <CheckCircleIcon sx={{ color: region?.color, fontSize: 20 }} />
              <Typography
                variant="subtitle1"
                sx={{ color: bneColors.neutral[50], fontWeight: 600 }}
              >
                {region?.displayName}
              </Typography>
            </Box>
            <Typography variant="body2" sx={{ color: bneColors.neutral[400] }}>
              {region?.countries.length} countries available
            </Typography>
          </Box>

          {/* Country Selection */}
          <Box sx={{ mb: 2 }}>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                mb: 2,
              }}
            >
              <Typography
                variant="subtitle2"
                sx={{ color: bneColors.neutral[300], fontWeight: 500 }}
              >
                Country Selection
              </Typography>
              <Button
                size="small"
                onClick={() => setShowCountries(!showCountries)}
                sx={{
                  color: bneColors.primary[400],
                  textTransform: 'none',
                  fontSize: '0.75rem',
                }}
              >
                {showCountries ? 'Hide' : 'Show'} Countries
              </Button>
            </Box>

            {/* Selection Summary */}
            <Box sx={{ mb: 2 }}>
              <Chip
                label={
                  selectedCountries.length === 0
                    ? 'Whole region selected'
                    : `${selectedCountries.length} / ${region?.countries.length} countries`
                }
                size="small"
                sx={{
                  bgcolor: selectedCountries.length === 0
                    ? bneColors.accent[900]
                    : bneColors.primary[900],
                  color: bneColors.neutral[200],
                  fontWeight: 500,
                }}
              />
            </Box>

            {/* Country List */}
            <Collapse in={showCountries}>
              <Box
                sx={{
                  maxHeight: 300,
                  overflowY: 'auto',
                  bgcolor: bneColors.neutral[900],
                  borderRadius: 1,
                  p: 1.5,
                  mb: 2,
                  '&::-webkit-scrollbar': {
                    width: '6px',
                  },
                  '&::-webkit-scrollbar-track': {
                    bgcolor: bneColors.neutral[800],
                    borderRadius: '3px',
                  },
                  '&::-webkit-scrollbar-thumb': {
                    bgcolor: bneColors.neutral[600],
                    borderRadius: '3px',
                    '&:hover': {
                      bgcolor: bneColors.neutral[500],
                    },
                  },
                }}
              >
                <FormControl component="fieldset" fullWidth>
                  <FormGroup>
                    {region?.countries.map((countryCode) => (
                      <FormControlLabel
                        key={countryCode}
                        control={
                          <Checkbox
                            checked={selectedCountries.includes(countryCode)}
                            onChange={() => handleCountryToggle(countryCode)}
                            icon={<RadioButtonUncheckedIcon fontSize="small" />}
                            checkedIcon={<CheckCircleIcon fontSize="small" />}
                            sx={{
                              color: bneColors.neutral[500],
                              '&.Mui-checked': {
                                color: region?.color,
                              },
                            }}
                          />
                        }
                        label={
                          <Typography
                            variant="body2"
                            sx={{ color: bneColors.neutral[300], fontSize: '0.875rem' }}
                          >
                            {countryCode}
                          </Typography>
                        }
                      />
                    ))}
                  </FormGroup>
                </FormControl>
              </Box>

              {/* Selection Actions */}
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button
                  size="small"
                  onClick={handleSelectAllCountries}
                  disabled={isAllSelected}
                  sx={{
                    flex: 1,
                    color: bneColors.accent[400],
                    borderColor: bneColors.accent[700],
                    textTransform: 'none',
                    fontSize: '0.75rem',
                    '&:hover': {
                      borderColor: bneColors.accent[500],
                      bgcolor: `${bneColors.accent[900]}50`,
                    },
                  }}
                  variant="outlined"
                >
                  Select All
                </Button>
                <Button
                  size="small"
                  onClick={handleDeselectAllCountries}
                  disabled={selectedCountries.length === 0}
                  sx={{
                    flex: 1,
                    color: bneColors.neutral[400],
                    borderColor: bneColors.neutral[700],
                    textTransform: 'none',
                    fontSize: '0.75rem',
                    '&:hover': {
                      borderColor: bneColors.neutral[500],
                      bgcolor: `${bneColors.neutral[800]}50`,
                    },
                  }}
                  variant="outlined"
                >
                  Clear
                </Button>
              </Box>
            </Collapse>
          </Box>

          {/* Action Buttons */}
          <Box sx={{ mt: 'auto', pt: 3 }}>
            <Button
              fullWidth
              variant="outlined"
              onClick={onClearSelection}
              sx={{
                color: bneColors.neutral[300],
                borderColor: bneColors.neutral[600],
                textTransform: 'none',
                py: 1.5,
                fontWeight: 500,
                '&:hover': {
                  borderColor: bneColors.neutral[400],
                  bgcolor: `${bneColors.neutral[700]}30`,
                },
              }}
            >
              Change Region
            </Button>
          </Box>
        </>
      )}
    </Paper>
  );
}
