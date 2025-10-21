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
  Alert,
  CircularProgress,
} from '@mui/material';
import { Add as AddIcon, Edit as EditIcon, FileCopy as CloneIcon, CheckCircle as ActivateIcon } from '@mui/icons-material';
import { api } from '../api/client';

export default function Configuration() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState(null);
  const [formData, setFormData] = useState({ name: '', config_data: {} });

  const { data: configurations, isLoading } = useQuery('configurations', () =>
    api.configurations.list().then(res => res.data)
  );

  const createMutation = useMutation((data) => api.configurations.create(data), {
    onSuccess: () => {
      queryClient.invalidateQueries('configurations');
      setDialogOpen(false);
    },
  });

  const updateMutation = useMutation(({ id, data }) => api.configurations.update(id, data), {
    onSuccess: () => {
      queryClient.invalidateQueries('configurations');
      setDialogOpen(false);
    },
  });

  const activateMutation = useMutation((id) => api.configurations.update(id, { is_active: true }), {
    onSuccess: () => {
      queryClient.invalidateQueries('configurations');
    },
  });

  const handleOpenDialog = (config = null) => {
    if (config) {
      setEditingConfig(config);
      setFormData({ name: config.name, config_data: config.config_data });
    } else {
      setEditingConfig(null);
      setFormData({ name: '', config_data: {} });
    }
    setDialogOpen(true);
  };

  const handleClone = (config) => {
    setEditingConfig(null);
    setFormData({ name: `${config.name} (Clone)`, config_data: config.config_data });
    setDialogOpen(true);
  };

  const handleSubmit = () => {
    if (editingConfig) {
      updateMutation.mutate({ id: editingConfig.id, data: formData });
    } else {
      createMutation.mutate(formData);
    }
  };

  if (isLoading) {
    return <CircularProgress />;
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>Configuration Management</Typography>
      <Button startIcon={<AddIcon />} variant="contained" onClick={() => handleOpenDialog()}>Create Configuration</Button>

      <Card sx={{ mt: 2 }}>
        <CardContent>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Version</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Created At</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {configurations && configurations.map(config => (
                  <TableRow key={config.id}>
                    <TableCell>{config.name}</TableCell>
                    <TableCell>{config.version}</TableCell>
                    <TableCell>
                      {config.is_active ? (
                        <Chip label="Active" color="success" size="small" />
                      ) : (
                        <Chip label="Inactive" size="small" />
                      )}
                    </TableCell>
                    <TableCell>{new Date(config.created_at).toLocaleString()}</TableCell>
                    <TableCell>
                      <IconButton onClick={() => handleOpenDialog(config)}><EditIcon /></IconButton>
                      <IconButton onClick={() => handleClone(config)}><CloneIcon /></IconButton>
                      {!config.is_active && (
                        <IconButton onClick={() => activateMutation.mutate(config.id)}><ActivateIcon /></IconButton>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editingConfig ? 'Edit' : 'Create'} Configuration</DialogTitle>
        <DialogContent>
          <TextField
            label="Name"
            fullWidth
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            sx={{ mt: 2 }}
          />
          <TextField
            label="Configuration Data (JSON)"
            fullWidth
            multiline
            rows={20}
            value={JSON.stringify(formData.config_data, null, 2)}
            onChange={(e) => {
              try {
                setFormData({ ...formData, config_data: JSON.parse(e.target.value) });
              } catch (error) {
                // Ignore JSON parsing errors while typing
              }
            }}
            sx={{ mt: 2, fontFamily: 'monospace' }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleSubmit} variant="contained">{editingConfig ? 'Update' : 'Create'}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}