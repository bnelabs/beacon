import React, { useEffect, useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Divider,
  FormControl,
  FormGroup,
  FormControlLabel,
  Checkbox,
  Chip,
  Button,
  CircularProgress,
  Alert,
  Collapse,
  IconButton,
} from '@mui/material';
import { bneColors } from '../../theme/bneTheme';
import StorageIcon from '@mui/icons-material/Storage';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import KeyIcon from '@mui/icons-material/Key';
import axios from 'axios';

interface DataSource {
  id: number;
  name: string;
  plugin_type: string;
  description: string;
  registration_url?: string;
  registration_required?: boolean;
  free_tier_limits?: string;
  coverage_description?: string;
  enabled: boolean;
}

interface DataSourceSelectorProps {
  selectedRegion: string | null;
  selectedCountries: string[];
  selectedSources: number[];
  onSourcesChange: (sourceIds: number[]) => void;
  onProceed: () => void;
}

export default function DataSourceSelector({
  selectedRegion,
  selectedCountries,
  selectedSources,
  onSourcesChange,
  onProceed,
}: DataSourceSelectorProps) {
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedSource, setExpandedSource] = useState<number | null>(null);

  // Fetch data sources
  useEffect(() => {
    const fetchDataSources = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await axios.get('http://localhost:3456/api/v1/sources');
        setDataSources(response.data.filter((ds: DataSource) => ds.enabled));
      } catch (err) {
        console.error('Failed to fetch data sources:', err);
        setError('Failed to load data sources');
      } finally {
        setLoading(false);
      }
    };

    fetchDataSources();
  }, []);

  const handleSourceToggle = (sourceId: number) => {
    if (selectedSources.includes(sourceId)) {
      onSourcesChange(selectedSources.filter((id) => id !== sourceId));
    } else {
      onSourcesChange([...selectedSources, sourceId]);
    }
  };

  const handleSelectAll = () => {
    onSourcesChange(dataSources.map((ds) => ds.id));
  };

  const handleDeselectAll = () => {
    onSourcesChange([]);
  };

  const handleToggleInfo = (sourceId: number) => {
    setExpandedSource(expandedSource === sourceId ? null : sourceId);
  };

  const isAllSelected = selectedSources.length === dataSources.length;
  const canProceed = selectedRegion && selectedSources.length > 0;

  if (loading) {
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
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <CircularProgress size={40} sx={{ color: bneColors.primary[500] }} />
      </Paper>
    );
  }

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
        <StorageIcon sx={{ color: bneColors.accent[400], fontSize: 28 }} />
        <Typography
          variant="h6"
          sx={{
            color: bneColors.neutral[50],
            fontWeight: 600,
            flex: 1,
          }}
        >
          Data Sources
        </Typography>
      </Box>

      <Divider sx={{ borderColor: bneColors.neutral[700], mb: 3 }} />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Selection Summary */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="body2" sx={{ color: bneColors.neutral[400], mb: 1 }}>
          {selectedRegion
            ? `Available data sources for ${selectedRegion.replace('_', ' ')}`
            : 'Select a region first to see available data sources'}
        </Typography>
        <Chip
          label={`${selectedSources.length} / ${dataSources.length} sources selected`}
          size="small"
          sx={{
            bgcolor: selectedSources.length > 0 ? bneColors.accent[900] : bneColors.neutral[800],
            color: bneColors.neutral[200],
            fontWeight: 500,
          }}
        />
      </Box>

      {/* Selection Actions */}
      <Box sx={{ display: 'flex', gap: 1, mb: 3 }}>
        <Button
          size="small"
          onClick={handleSelectAll}
          disabled={isAllSelected || dataSources.length === 0}
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
          onClick={handleDeselectAll}
          disabled={selectedSources.length === 0}
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
          Clear All
        </Button>
      </Box>

      {/* Data Sources List */}
      <Box
        sx={{
          flex: 1,
          overflowY: 'auto',
          mb: 3,
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
            {dataSources.map((source) => (
              <Box key={source.id} sx={{ mb: 1 }}>
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    bgcolor: selectedSources.includes(source.id)
                      ? `${bneColors.accent[900]}30`
                      : bneColors.neutral[900],
                    borderRadius: 1.5,
                    border: selectedSources.includes(source.id)
                      ? `1px solid ${bneColors.accent[700]}`
                      : `1px solid ${bneColors.neutral[800]}`,
                    p: 1.5,
                    transition: 'all 0.2s',
                    '&:hover': {
                      borderColor: bneColors.neutral[600],
                      bgcolor: selectedSources.includes(source.id)
                        ? `${bneColors.accent[900]}40`
                        : `${bneColors.neutral[800]}50`,
                    },
                  }}
                >
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={selectedSources.includes(source.id)}
                        onChange={() => handleSourceToggle(source.id)}
                        icon={<CheckCircleIcon fontSize="small" sx={{ opacity: 0.3 }} />}
                        checkedIcon={<CheckCircleIcon fontSize="small" />}
                        sx={{
                          color: bneColors.neutral[500],
                          '&.Mui-checked': {
                            color: bneColors.accent[500],
                          },
                        }}
                      />
                    }
                    label={
                      <Box sx={{ flex: 1 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Typography
                            variant="subtitle2"
                            sx={{ color: bneColors.neutral[200], fontWeight: 500 }}
                          >
                            {source.name}
                          </Typography>
                          {source.registration_required && (
                            <KeyIcon
                              sx={{
                                fontSize: 14,
                                color: bneColors.secondary[500],
                              }}
                            />
                          )}
                        </Box>
                        {source.coverage_description && (
                          <Typography
                            variant="caption"
                            sx={{ color: bneColors.neutral[400], display: 'block', mt: 0.5 }}
                          >
                            {source.coverage_description}
                          </Typography>
                        )}
                      </Box>
                    }
                    sx={{ m: 0, flex: 1 }}
                  />
                  <IconButton
                    size="small"
                    onClick={() => handleToggleInfo(source.id)}
                    sx={{
                      color: bneColors.neutral[500],
                      '&:hover': {
                        color: bneColors.neutral[300],
                      },
                    }}
                  >
                    <InfoOutlinedIcon fontSize="small" />
                  </IconButton>
                </Box>

                {/* Expanded Info */}
                <Collapse in={expandedSource === source.id}>
                  <Box
                    sx={{
                      mt: 1,
                      p: 2,
                      bgcolor: bneColors.neutral[900],
                      borderRadius: 1,
                      border: `1px solid ${bneColors.neutral[800]}`,
                    }}
                  >
                    <Typography
                      variant="body2"
                      sx={{ color: bneColors.neutral[300], mb: 1.5 }}
                    >
                      {source.description}
                    </Typography>

                    {source.registration_required && source.registration_url && (
                      <Box sx={{ mb: 1.5 }}>
                        <Typography
                          variant="caption"
                          sx={{ color: bneColors.secondary[400], fontWeight: 500 }}
                        >
                          Registration required
                        </Typography>
                        <Typography
                          variant="caption"
                          sx={{ color: bneColors.neutral[400], display: 'block' }}
                        >
                          Get API key at:{' '}
                          <a
                            href={source.registration_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: bneColors.primary[400] }}
                          >
                            {source.registration_url}
                          </a>
                        </Typography>
                      </Box>
                    )}

                    {source.free_tier_limits && (
                      <Box>
                        <Typography
                          variant="caption"
                          sx={{ color: bneColors.accent[400], fontWeight: 500 }}
                        >
                          Free tier limits
                        </Typography>
                        <Typography
                          variant="caption"
                          sx={{ color: bneColors.neutral[400], display: 'block' }}
                        >
                          {source.free_tier_limits}
                        </Typography>
                      </Box>
                    )}
                  </Box>
                </Collapse>
              </Box>
            ))}
          </FormGroup>
        </FormControl>
      </Box>

      {/* Proceed Button */}
      <Box sx={{ mt: 'auto' }}>
        <Button
          fullWidth
          variant="contained"
          onClick={onProceed}
          disabled={!canProceed}
          sx={{
            bgcolor: bneColors.accent[600],
            color: bneColors.neutral[50],
            textTransform: 'none',
            py: 1.5,
            fontWeight: 600,
            fontSize: '1rem',
            '&:hover': {
              bgcolor: bneColors.accent[500],
            },
            '&:disabled': {
              bgcolor: bneColors.neutral[800],
              color: bneColors.neutral[600],
            },
          }}
        >
          Load Data Catalogue
        </Button>
        {!canProceed && (
          <Typography
            variant="caption"
            sx={{
              color: bneColors.neutral[500],
              display: 'block',
              textAlign: 'center',
              mt: 1,
            }}
          >
            {!selectedRegion
              ? 'Select a region first'
              : 'Select at least one data source'}
          </Typography>
        )}
      </Box>
    </Paper>
  );
}
