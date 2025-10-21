import { useState } from 'react';
import { useMutation } from 'react-query';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Card, CardContent, TextField, Typography, Alert } from '@mui/material';
import { api } from '../api/client';

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);

  const loginMutation = useMutation(api.auth.login, {
    onSuccess: (data) => {
      localStorage.setItem('token', data.data.access_token);
      navigate('/');
    },
    onError: (err) => {
      setError(err.userFriendlyMessage || err.message || 'Invalid email or password');
    },
  });

  const handleLogin = () => {
    loginMutation.mutate({ username: email, password });
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
      <Card sx={{ minWidth: 400 }}>
        <CardContent>
          <Typography variant="h5" gutterBottom>Login</Typography>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField
            label="Email"
            fullWidth
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            label="Password"
            type="password"
            fullWidth
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            sx={{ mb: 2 }}
          />
          <Button
            variant="contained"
            fullWidth
            onClick={handleLogin}
            disabled={loginMutation.isLoading}
          >
            {loginMutation.isLoading ? 'Logging in...' : 'Login'}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
