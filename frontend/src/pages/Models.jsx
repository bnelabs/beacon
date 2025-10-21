import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from 'react-query';
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  CircularProgress,
} from '@mui/material';
import { Promote as PromoteIcon, CheckCircle as PromotedIcon } from '@mui/icons-material';
import { api } from '../api/client';

import { Tabs, Tab } from '@mui/material';

function TabPanel({ children, value, index }) {
  return (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

export default function Models() {
  const queryClient = useQueryClient();
  const [promoteDialogOpen, setPromoteDialogOpen] = useState(false);
  const [modelToPromote, setModelToPromote] = useState(null);
  const [activeTab, setActiveTab] = useState(0);

  const { data: models, isLoading } = useQuery('models', () =>
    api.models.list().then(res => res.data)
  );

  const promoteMutation = useMutation((id) => api.models.promote(id), {
    onSuccess: () => {
      queryClient.invalidateQueries('models');
      setPromoteDialogOpen(false);
    },
  });

  const handlePromote = (id) => {
    setModelToPromote(id);
    setPromoteDialogOpen(true);
  };

  const confirmPromote = () => {
    if (modelToPromote) {
      promoteMutation.mutate(modelToPromote);
    }
  };

  if (isLoading) {
    return <CircularProgress />;
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>Model Registry</Typography>

      <Tabs value={activeTab} onChange={(e, v) => setActiveTab(v)}>
        <Tab label="Model Versions" />
        <Tab label="Monitoring" />
      </Tabs>

      <TabPanel value={activeTab} index={0}>
        <Card sx={{ mt: 2 }}>
          <CardContent>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Model</TableCell>
                    <TableCell>Version</TableCell>
                    <TableCell>Stage</TableCell>
                    <TableCell>Job ID</TableCell>
                    <TableCell>Created At</TableCell>
                    <TableCell>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {models && models.map(model => (
                    <TableRow key={model.id}>
                      <TableCell>{model.name}</TableCell>
                      <TableCell>{model.version}</TableCell>
                      <TableCell>
                        {model.stage === 'Production' ? (
                          <Chip label="Production" color="success" size="small" icon={<PromotedIcon />} />
                        ) : (
                          <Chip label={model.stage} size="small" />
                        )}
                      </TableCell>
                      <TableCell>{model.job_id}</TableCell>
                      <TableCell>{new Date(model.created_at).toLocaleString()}</TableCell>
                      <TableCell>
                        {model.stage !== 'Production' && (
                          <IconButton onClick={() => handlePromote(model.id)} disabled={promoteMutation.isLoading}>
                            <PromoteIcon />
                          </IconButton>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      </TabPanel>

  const { data: driftReport } = useQuery(
    ['driftReport', modelToPromote], // Use modelToPromote as a proxy for selected production model
    () => api.models.getDriftReport(modelToPromote).then(res => res.data),
    {
      enabled: !!modelToPromote && models?.find(m => m.id === modelToPromote)?.stage === 'Production',
    }
  );

      <TabPanel value={activeTab} index={1}>
        <Card sx={{ mt: 2 }}>
          <CardContent>
            <Typography variant="h6">Model Monitoring</Typography>
            {driftReport ? (
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle1">Data Drift Report</Typography>
                <Alert severity={driftReport.data_drift.data.metrics.dataset_drift ? 'error' : 'success'} sx={{ mt: 1 }}>
                  Dataset Drift: {driftReport.data_drift.data.metrics.dataset_drift ? 'Detected' : 'Not Detected'}
                </Alert>
                {driftReport.data_drift.data.metrics.dataset_drift && (
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    Number of drifted features: {driftReport.data_drift.data.metrics.n_drifted_features}
                  </Typography>
                )}
                {/* You can add more detailed visualization of the drift report here */}
              </Box>
            ) : (
              <Alert severity="info" sx={{ mt: 2 }}>
                No drift report available for the selected production model.
              </Alert>
            )}

            <Box sx={{ mt: 4 }}>
              <Typography variant="h6">Retraining Policy</Typography>
              <FormControlLabel
                control={<Switch />}
                label="Enable Automated Retraining"
              />
              <TextField
                label="Performance Threshold (MAE)"
                type="number"
                size="small"
                sx={{ mt: 2, mr: 2 }}
              />
              <Button variant="contained" color="secondary">Retrain Now</Button>
            </Box>
          </CardContent>
        </Card>
      </TabPanel>

      <Dialog open={promoteDialogOpen} onClose={() => setPromoteDialogOpen(false)}>
        <DialogTitle>Promote Model</DialogTitle>
        <DialogContent>
          <Typography>Are you sure you want to promote this model to Production?</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPromoteDialogOpen(false)}>Cancel</Button>
          <Button onClick={confirmPromote} disabled={promoteMutation.isLoading}>
            {promoteMutation.isLoading ? 'Promoting...' : 'Promote'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
