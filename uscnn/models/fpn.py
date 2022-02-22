# import the necessary packages
from ..layers import MeshConv, MeshConvTranspose, ResBlock
from torch import nn
import os


class Up(nn.Module):
    def __init__(self, in_ch, out_ch, level, mesh_folder, bias=True):
        """
            use mesh_file for the mesh of one-level up
        """

        # make a call to the parent constructor
        super(Up, self).__init__()

        # build the path to the mesh file
        mesh_file = os.path.join(mesh_folder, "icosphere_{}.pkl".format(level))

        # MESHCONV.T
        self.up = MeshConvTranspose(out_ch, out_ch, mesh_file, stride=2)

        # cross connection
        self.conv = nn.Conv1d(in_ch, out_ch, kernel_size=1, stride=1)

    def forward(self, x1, x2):
        # upsample the previous pyramid layer
        x1 = self.up(x1)

        # cross connection from encoder
        x2 = self.conv(x2)

        # addition
        x = x1 + x2

        # return the computation of the layer
        return x


class Down(nn.Module):
    def __init__(self, in_ch, out_ch, level, mesh_folder, bias=True):
        """
            use the mesh_file for the mesh of one-level down
        """

        # make a call to the parent constructor
        super(Down, self).__init__()

        # res block
        self.conv = ResBlock(in_ch, in_ch, out_ch, level + 1, True, mesh_folder)

    def forward(self, x):
        # pass the input through the res block and return
        return self.conv(x)


class SphericalFPNet(nn.Module):
    def __init__(self, mesh_folder, in_ch, out_ch, max_level=5, min_level=0, fdim=16, fpn_dim=256):
        # make a call to the parent class constructor
        super(SphericalFPNet, self).__init__()

        # initialise the instance variables
        self.mesh_folder = mesh_folder
        self.fdim = fdim
        self.max_level = max_level
        self.min_level = min_level
        self.levels = max_level - min_level

        # initialise lists to store the encoder and decoder stages
        self.down, self.up = [], []

        # initial and final MESHCONV
        self.in_conv = MeshConv(in_ch, fdim, self.__meshfile(max_level), stride=1)
        self.out_conv_a = MeshConvTranspose(128, 128, self.__meshfile(max_level - 1), stride=2)
        self.out_conv_b = MeshConvTranspose(128, out_ch, self.__meshfile(max_level), stride=2)

        # backbone
        for i in range(self.levels):
            # compute the number of in, out channels, and level
            ch_in = int(fdim * (2 ** i))
            ch_out = int(fdim * (2 ** (i + 1)))
            lvl = max_level - i - 1

            # add a downsample block
            self.down.append(Down(ch_in, ch_out, lvl, mesh_folder))

        # 1x1 cross connection at lvl-0
        self.cross_conv = nn.Conv1d(ch_out, fpn_dim, kernel_size=1, stride=1)

        # feature pyramid
        for i in range(3):
            # compute the number of in, out channels, and level
            ch_in = int(fdim * (2 ** (self.levels - i - 1)))
            ch_out = fpn_dim
            lvl = min_level + i + 1

            # add an upsample block
            self.up.append(Up(ch_in, ch_out, min_level + i + 1, mesh_folder))

        # upsampling convolutions for detection stage
        self.conv_1a = MeshConvTranspose(fpn_dim, 128, self.__meshfile(1), stride=2)
        self.conv_1b = MeshConvTranspose(128, 128, self.__meshfile(2), stride=2)
        self.conv_1c = MeshConvTranspose(128, 128, self.__meshfile(3), stride=2)
        self.conv_2a = MeshConvTranspose(fpn_dim, 128, self.__meshfile(2), stride=2)
        self.conv_2b = MeshConvTranspose(128, 128, self.__meshfile(3), stride=2)
        self.conv_3a = MeshConvTranspose(fpn_dim, 128, self.__meshfile(3), stride=2)
        self.conv_4a = nn.Conv1d(fpn_dim, 128, kernel_size=1, stride=1)

        # initialise the modules
        self.down = nn.ModuleList(self.down)
        self.up = nn.ModuleList(self.up)

    def __meshfile(self, i):
        return os.path.join(self.mesh_folder, "icosphere_{}.pkl".format(i))

    def forward(self, x):
        # pass through initial MESHCONV
        x_d = [self.in_conv(x)]

        # loop through and pass the input through the encoder
        for i in range(self.levels):
            x_d.append(self.down[i](x_d[-1]))

        # initial cross connection at lvl-0
        x_u = [self.cross_conv(x_d[-1])]

        # feature pyramid
        x_u.append(self.up[0](x_u[-1], x_d[self.levels - 1]))
        x_u.append(self.up[1](x_u[-1], x_d[self.levels - 2]))
        x_u.append(self.up[2](x_u[-1], x_d[self.levels - 3]))

        # detection stage
        x1 = self.conv_1c(self.conv_1b(self.conv_1a(x_u[0])))
        x2 = self.conv_2b(self.conv_2a(x_u[1]))
        x3 = self.conv_3a(x_u[2])
        x4 = self.conv_4a(x_u[3])

        # add all the pyramid levels together
        x = x1 + x2 + x3 + x4

        # 4x upsample for final prediction
        x = self.out_conv_b(self.out_conv_a(x))

        # return the output of the model
        return x


# if __name__ == "__main__":
#     from torchinfo import summary

#     model = SphericalFPNet("uscnn/meshes", 4, 15, max_level=5, fdim=32)

#     summary(model, input_size=(1, 4, 10242))