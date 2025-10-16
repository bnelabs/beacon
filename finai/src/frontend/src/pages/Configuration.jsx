import { Typography, Box } from '@mui/material'

export default function Configuration() {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Configuration
      </Typography>
      <Typography variant="body1" color="text.secondary">
        Configure model parameters, data collection settings, and training options.
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        (Full implementation coming soon - will include model settings, data settings, and training settings)
      </Typography>
    </Box>
  )
}
