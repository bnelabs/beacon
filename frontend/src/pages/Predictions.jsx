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
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  CircularProgress,
  Tabs,
  Tab,
} from '@mui/material';
import { Add as AddIcon, UploadFile as UploadIcon } from '@mui/icons-material';
import { api } from '../api/client';

function TabPanel({ children, value, index }) {
  return (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

export default function Predictions() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState(0);
  const [startJobDialogOpen, setStartJobDialogOpen] = useState(false);
  const [newJob, setNewJob] = useState({ model_version_id: '', data_job_id: '' });
  const [scenarioFile, setScenarioFile] = useState(null);
  const [scenarioResult, setScenarioResult] = useState(null);

  const { data: models } = useQuery('models', () => api.models.list().then(res => res.data));
  const { data: dataJobs } = useQuery('completedDataJobs', () =>
    api.jobs.list({ job_type: 'data_collection', status: 'completed' }).then(res => res.data)
  );

  const runPredictionMutation = useMutation(api.jobs.create, {
    onSuccess: () => {
      queryClient.invalidateQueries('jobs');
      setStartJobDialogOpen(false);
    },
  });

  const runScenarioMutation = useMutation(api.scenarios.run, {
    onSuccess: (data) => {
      setScenarioResult(data.data);
    },
  });

  const handleRunPrediction = () => {
    runPredictionMutation.mutate({ job_type: 'prediction', parameters: newJob });
  };

  const handleRunScenario = () => {
    const formData = new FormData();
    formData.append('file', scenarioFile);
    runScenarioMutation.mutate({ model_version_id: newJob.model_version_id, file: formData });
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>Prediction Hub</Typography>

      <Tabs value={activeTab} onChange={(e, v) => setActiveTab(v)}>
        <Tab label="Batch Predictions" />
        <Tab label="Scenario Analysis" />
      </Tabs>

      <TabPanel value={activeTab} index={0}>
        <Card>
          <CardContent>
            <Typography variant="h6">Run a new prediction job</Typography>
            <Button sx={{ mt: 2 }} startIcon={<AddIcon />} variant="contained" onClick={() => setStartJobDialogOpen(true)}>
              New Prediction Job
            </Button>
          </CardContent>
        </Card>
      </TabPanel>

      <TabPanel value={activeTab} index={1}>
        <Card>
          <CardContent>
            <Typography variant="h6">Run a new scenario</Typography>
            <FormControl fullWidth sx={{ mt: 2 }}>
              <InputLabel>Model Version</InputLabel>
              <Select
                value={newJob.model_version_id}
                label="Model Version"
                onChange={(e) => setNewJob({ ...newJob, model_version_id: e.target.value })}
              >
                {models && models.map(model => (
                  <MenuItem key={model.id} value={model.id}>
                    {model.name} - v{model.version}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button component="label" variant="outlined" startIcon={<UploadIcon />} sx={{ mt: 2 }}>
              Upload CSV
              <input type="file" hidden onChange={(e) => setScenarioFile(e.target.files[0])} />
            </Button>
            <Button sx={{ mt: 2, ml: 2 }} variant="contained" onClick={handleRunScenario} disabled={!scenarioFile || !newJob.model_version_id}>
              Run Scenario
            </Button>
            {scenarioResult && (
              <TableContainer sx={{ mt: 2 }}>
                <Table>
                  <TableHead>
                    <TableRow>
                      {Object.keys(scenarioResult[0]).map(key => <TableCell key={key}>{key}</TableCell>)}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {scenarioResult.map((row, i) => (
                      <TableRow key={i}>
                        {Object.values(row).map((value, j) => <TableCell key={j}>{value}</TableCell>)}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </CardContent>
        </Card>
      </TabPanel>

      <Dialog open={startJobDialogOpen} onClose={() => setStartJobDialogOpen(false)}>
        <DialogTitle>Start Prediction Job</DialogTitle>
        <DialogContent>
          <FormControl fullWidth sx={{ mt: 2 }}>
            <InputLabel>Model Version</InputLabel>
            <Select
              value={newJob.model_version_id}
              label="Model Version"
              onChange={(e) => setNewJob({ ...newJob, model_version_id: e.target.value })}
            >
              {models && models.map(model => (
                <MenuItem key={model.id} value={model.id}>
                  {model.name} - v{model.version}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth sx={{ mt: 2 }}>
            <InputLabel>Data Job</InputLabel>
            <Select
              value={newJob.data_job_id}
              label="Data Job"
              onChange={(e) => setNewJob({ ...newJob, data_job_id: e.target.value })}
            >
              {dataJobs && dataJobs.map(job => (
                <MenuItem key={job.id} value={job.id}>
                  Job #{job.id} - {new Date(job.completed_at).toLocaleString()}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStartJobDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleRunPrediction} variant="contained">Start Job</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
