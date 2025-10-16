import { Typography, Box } from '@mui/material'

export default function SystemStatus() {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Status
      </Typography>
      <Typography variant="body1" color="text.secondary">
        Monitor system health, resource usage, and get recommendations for optimization.
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        (Full implementation coming soon - will include CPU/RAM/GPU monitoring, resource recommendations)
      </Typography>
    </Box>
  )
}
