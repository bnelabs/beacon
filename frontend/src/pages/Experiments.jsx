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
import { Add as AddIcon, Assessment as AssessmentIcon } from '@mui/icons-material';
import { api } from '../api/client';

function TabPanel({ children, value, index }) {
  return (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

export default function Experiments() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState(0);
  const [startExperimentDialogOpen, setStartExperimentDialogOpen] = useState(false);
  const [newExperiment, setNewExperiment] = useState({ name: '', description: '' });

  const { data: experiments, isLoading } = useQuery('experiments', () =>
    api.experiments.list().then(res => res.data)
  );

  const createExperimentMutation = useMutation(api.experiments.create, {
    onSuccess: () => {
      queryClient.invalidateQueries('experiments');
      setStartExperimentDialogOpen(false);
    },
  });

  const handleStartExperiment = () => {
    createExperimentMutation.mutate(newExperiment);
  };

  if (isLoading) {
    return <CircularProgress />;
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>Experiment Tracking Hub</Typography>

      <Tabs value={activeTab} onChange={(e, v) => setActiveTab(v)}>
        <Tab label="Experiments" />
        <Tab label="Runs" />
      </Tabs>

      <TabPanel value={activeTab} index={0}>
        <Card>
          <CardContent>
            <Button startIcon={<AddIcon />} variant="contained" onClick={() => setStartExperimentDialogOpen(true)}>
              New Experiment
            </Button>
            <TableContainer sx={{ mt: 2 }}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Description</TableCell>
                    <TableCell>Created At</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {experiments && experiments.map(exp => (
                    <TableRow key={exp.id}>
                      <TableCell>{exp.name}</TableCell>
                      <TableCell>{exp.description}</TableCell>
                      <TableCell>{new Date(exp.created_at).toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      </TabPanel>

      <TabPanel value={activeTab} index={1}>
        <Card>
          <CardContent>
            <Typography variant="h6">All Runs</Typography>
            {/* Placeholder for runs table */}
            <Alert severity="info" sx={{ mt: 2 }}>
              This is a placeholder for the runs table. It will be implemented in a future step.
            </Alert>
          </CardContent>
        </Card>
      </TabPanel>

      <Dialog open={startExperimentDialogOpen} onClose={() => setStartExperimentDialogOpen(false)}>
        <DialogTitle>Start New Experiment</DialogTitle>
        <DialogContent>
          <TextField
            label="Experiment Name"
            fullWidth
            value={newExperiment.name}
            onChange={(e) => setNewExperiment({ ...newExperiment, name: e.target.value })}
            sx={{ mt: 2 }}
          />
          <TextField
            label="Description"
            fullWidth
            multiline
            rows={4}
            value={newExperiment.description}
            onChange={(e) => setNewExperiment({ ...newExperiment, description: e.target.value })}
            sx={{ mt: 2 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStartExperimentDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleStartExperiment} variant="contained">Create</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
